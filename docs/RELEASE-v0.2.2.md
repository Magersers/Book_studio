# Book Studio v0.2.2

Audiobook speech can now run through several RouterAI requests at once. Open **Speech / RouterAI** (**Озвучка / RouterAI**) and set **Concurrent requests** (**Параллельных запросов**): the default is **3**, with a range of **1–8**. Use 1 for sequential processing or reduce the value if the provider limits requests.

- Each speech worker owns its API client and HTTP session. At most the selected number of segments are submitted at once; local music and sound effects continue to share one serial local runtime.
- Finished fragments are saved individually. Chapters are assembled in the book's original order, with the assigned voices and performance directions. Changing the concurrency setting preserves existing speech cache identities.
- An API failure stops new submissions while successful work already in flight is checkpointed. Paid speech requests are not retried automatically. Continue explicitly after an error; an interrupted request may already have been billed by the provider.
- Pausing drains the submitted work before entering the saved pause state. Stopping or force-closing API speech preserves completed fragments for resume.
- Checkboxes now have explicit square borders and visible check marks in enabled and disabled states. The studio, audiobook controls and detailed sound tab use the same visual states.
- Busy local-model preparation and generation wait with progress, cancellation and a finite timeout. Existing downloaded weights are retained, and a crashed process does not leave an active OS lock.

Validation coverage includes bounded concurrency, source-order assembly, checkpoints after failure and interruption, pause/cancellation, independent HTTP clients, preference validation and restoration, and real subprocess lock contention. Qt offscreen previews verify the checkbox states in the studio and audiobook sound controls. These checks use test fixtures; they do not require paid speech synthesis, model downloads or GPU inference.

Existing books, voices, tags, audio checkpoints, API keys and downloaded model weights remain in place during an update. Close the app before copying release files into the existing installation directory.
