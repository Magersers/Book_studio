# Book Studio v0.2.0

This release connects the voice library and audiobook renderer to Fish Audio Drama 3 through RouterAI using saved Fish voice IDs.

- The Russian catalogue contains ten male and ten female public voices, ordered by Fish Audio's `task_count` at the recorded snapshot time. Gender labels and descriptions come from Fish Audio. Identically named voices remain separate by their stable IDs and authors.
- Catalogue avatars contain metadata and public preview links. No original voice recordings or API credentials are distributed. Public availability does not establish a licence for every intended use.
- New catalogue profiles appear under `Fish Audio · RU`, grouped by gender and use case. Importing the same snapshot again preserves edits, existing folder assignments and archived profiles.
- Both studio synthesis and audiobook narration use the selected Fish ID. Metadata-only profiles no longer require a local WAV or transcript. Local recordings without a linked Fish ID show a clear instruction instead of silently using the default speaker.
- RouterAI's API key remains in local protected settings. One synthesis POST is attempted; a failed or cancelled request is not automatically submitted again.
- Updating the installed application preserves its data, books, history, local recordings and model files. Older audio is not overwritten merely by starting the new version.

The snapshot can be refreshed explicitly with `python tools/update_fish_catalog.py`. It requests only public catalogue metadata from the documented Fish Audio List Models API, with `language=ru`, `tag=male/female` and `sort_by=task_count`.
