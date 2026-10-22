"""Bounded API speech workers; durable SQLite publication stays on the caller."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
import queue
import threading

import avatar_store as store


def worker_count(pipeline, meta):
    if not getattr(pipeline, 'supports_parallel_book', False):
        return 1
    value = meta.get('api_workers', getattr(pipeline, 'config', {}).get('api_workers', 3))
    return max(1, min(8, value)) if type(value) is int else 3


def render_segments(book_id, pipeline, db, chapter, characters, meta, voices,
                    done, total, progress, control):
    """Submit at most N segments, drain every success, never retry a paid call.

    Each slot owns its Pipeline/Session. Workers only create speech files; the
    calling thread does all SQLite commits, normalization, joins and UI events.
    Failed jobs stop new submissions, while already submitted jobs can finish
    and checkpoint. Chapter assembly later reads SQLite in source order.
    """
    import book_engine as books
    import book_state as state

    jobs = []
    for row in db.execute('SELECT * FROM segments WHERE chapter=? ORDER BY id', (chapter['id'],)).fetchall():
        segment = dict(row)
        plan = books.segment_plan(segment, chapter, characters, meta)
        signature = books.plan_signature(plan, voices, meta['seed'])
        if segment['signature'] == signature and Path(segment['wav']).is_file():
            done += 1
        else:
            jobs.append((segment, plan, signature))
    if not jobs:
        progress(done / max(1, total), f'Озвучено {done}/{total} фрагментов · {done*100/max(1,total):.1f}%')
        control.boundary(chapter['id'])
        return done

    maximum = min(worker_count(pipeline, meta), len(jobs))
    slots = []
    events = queue.Queue(maxsize=64)
    levels = {}
    pending = {}
    cursor = 0
    failure = None
    worker_failed = threading.Event()
    cache = books.folder(book_id) / 'audio'
    cache.mkdir(exist_ok=True)

    def check_cancel():
        books.cancelled(book_id)
        pipeline.check_book_cancel()

    def report(slot, segment_id, index, value, message):
        try:
            events.put_nowait((slot, segment_id, index, value, message))
        except queue.Full:
            pass  # Status is lossy; audio and checkpoints are never queued here.

    def synthesize(slot, job):
        segment, plan, signature = job
        client = slots[slot]
        clips = []
        review = False
        for part_index, part in enumerate(plan):
            check_cancel()
            target = cache / (f'{segment["id"]:08d}.wav' if len(plan) == 1
                              else f'{segment["id"]:08d}-part-{part_index:03d}.wav')
            if part.get('sound_file'):
                clips.append(str(part['sound_file']))
                continue
            voice = voices[part['avatar']]
            options = ({'narrator_style': part['narrator_style']}
                       if part.get('narrator_style') and getattr(client, 'supports_narrator_styles', False) else {})
            if getattr(client, 'supports_progress', False):
                options.update(progress=lambda value, message, index=part_index:
                               report(slot, segment['id'], index, value, message), cancel=check_cancel)
            clips.append(client.synthesize_book_clip(
                books.pipeline_voice(voice, client), part['text'], voice.get('transcript', ''),
                meta['seed'], target, **options))
            review = review or bool(store.load_json(target.with_suffix('.cleanup.json'), {}).get('needs_review'))
        return clips, review

    def work(slot, job):
        try:
            return synthesize(slot, job)
        except BaseException:
            worker_failed.set()
            raise

    def publish(job, result):
        segment, plan, signature = job
        clips, review = result
        wav = str(cache / f'{segment["id"]:08d}.wav')
        if len(plan) > 1:
            books.stitch(clips, Path(wav), book_id, pause_ms=60)
        if not plan:
            import numpy as np
            import soundfile as sf
            sf.write(wav, np.zeros(240, dtype='float32'), 24000)
        if plan:
            wav = books.assemble_chapter_segments(book_id, [dict(id=segment['id'], wav=wav)], [plan])[0]
        db.execute('UPDATE segments SET wav=?,signature=?,audio_review=? WHERE id=?',
                   (wav, signature, int(review), segment['id']))
        db.commit()

    try:
        for _ in range(maximum):
            slots.append(pipeline.fork_book_pipeline())
        with ThreadPoolExecutor(max_workers=maximum, thread_name_prefix='Book-RouterAI') as executor:
            free = list(range(maximum))
            while pending or cursor < len(jobs):
                if failure is None:
                    try:
                        check_cancel()
                    except BaseException as exc:
                        failure = exc
                # Drain in-flight requests before a pause blocks the coordinator;
                # successes are saved even when they finish out of order.
                paused = state.requested(book_id) == 'pause'
                if not pending and paused and failure is None:
                    control.boundary(chapter['id'])
                    continue
                while (free and cursor < len(jobs) and failure is None
                       and not paused and not worker_failed.is_set()):
                    slot = free.pop()
                    job = jobs[cursor]
                    cursor += 1
                    levels[slot] = 0.
                    future = executor.submit(work, slot, job)
                    pending[future] = (slot, job)
                if not pending:
                    break
                finished, _ = wait(pending, timeout=.1, return_when=FIRST_COMPLETED)
                while True:
                    try:
                        slot, segment_id, index, value, message = events.get_nowait()
                    except queue.Empty:
                        break
                    active = next((job for s, job in pending.values() if s == slot), None)
                    if active is not None and active[0]['id'] == segment_id:
                        levels[slot] = min(.99, (index + (value or 0)) / max(1, len(active[1])))
                        progress((done + sum(levels.values())) / max(1, total),
                                 f'Параллельная озвучка: {len(pending)} · ' + message)
                # Observe every failure in this completion batch before refilling.
                completed = []
                for future in finished:
                    slot, job = pending.pop(future)
                    free.append(slot)
                    levels.pop(slot, None)
                    try:
                        completed.append((job, future.result()))
                    except BaseException as exc:
                        if failure is None:
                            failure = exc
                for job, result in completed:
                    try:
                        publish(job, result)
                        done += 1
                        progress(done / max(1, total), f'Озвучено {done}/{total} фрагментов · {done*100/max(1,total):.1f}%')
                        # A pause may arrive between checking control.json and
                        # boundary(). Never enter its blocking pause loop while
                        # other requests still need durable publication.
                        state.snapshot(book_id, chapter['id'])
                    except BaseException as exc:
                        if failure is None:
                            failure = exc
            if failure is not None:
                state.snapshot(book_id, chapter['id'])
                raise failure
            control.boundary(chapter['id'])
    finally:
        for client in slots:
            client.close()
    return done
