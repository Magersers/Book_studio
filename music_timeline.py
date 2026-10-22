"""Resolve score boundaries from measured audio, never predicted speech speed."""
import math
import soundfile as sf


def segment_timing(paths, segment_ids, pauses=(), initial_offset=0):
    if len(paths) != len(segment_ids):
        raise ValueError('Число записей и фрагментов не совпало.')
    position = float(initial_offset)
    result = []
    for index, (path, segment_id) in enumerate(zip(paths, segment_ids)):
        info = sf.info(str(path))
        seconds = info.frames / info.samplerate
        result.append(dict(segment_id=int(segment_id), start_seconds=position, end_seconds=position + seconds))
        position += seconds
        if index < len(paths) - 1 and index < len(pauses):
            position += max(0, float(pauses[index])) / 1000
    return result


def cue_times(plan, timing, duration):
    measured = []
    previous = -1.
    for row in timing:
        first, last = float(row['start_seconds']), float(row['end_seconds'])
        if not math.isfinite(first + last) or first < 0 or last <= first or first < previous - .001 or last > duration + .02:
            raise ValueError('Музыкальные таймкоды не совпадают с готовой речью.')
        previous = last
        measured.append(dict(row, start_seconds=first, end_seconds=min(last, duration)))
    result = []
    for cue in plan.get('cues', []):
        selected = [r for r in measured if cue['start_segment'] <= r['segment_id'] <= cue['end_segment']]
        if selected:
            result.append(dict(cue, start_seconds=selected[0]['start_seconds'], end_seconds=selected[-1]['end_seconds']))
    result.sort(key=lambda cue: cue['start_seconds'])
    for previous, current in zip(result, result[1:]):
        if current['start_seconds'] < previous['end_seconds'] - .001:
            raise ValueError('Музыкальные фрагменты перекрываются.')
    return result


def chunks(start, end, maximum=45., overlap=2.):
    """Each bounded synthesis chunk has room for a smooth adjacent crossfade."""
    if maximum <= overlap or overlap < 0 or end <= start:
        raise ValueError('Некорректная длина музыкального фрагмента.')
    count = max(1, math.ceil((end-start-overlap) / (maximum-overlap)))
    length = ((end-start) + overlap*(count-1)) / count
    for index in range(count):
        position = float(start) + index*(length-overlap)
        yield position, min(float(end), position+length)
