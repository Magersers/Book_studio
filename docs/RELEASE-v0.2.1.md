# Book Studio v0.2.1

Music and sound effect controls are now visible together above the audiobook tabs. They remain independent and both use the same optional local Stable Audio 3 Medium model.

- **Background music — AI** and **Sound effects — AI** appear in a highlighted **MUSIC AND SOUND EFFECTS** group. The detailed sound tab shares the same saved effect setting.
- The main studio includes a **Book music and sound effects** button that opens the book's sound tab. Its own background music checkbox continues to control studio speech.
- Audiobook playback/export controls wrap into two rows so the dialog fits a 1110 × 790 window. Both generation controls are disabled while a book is rendering or no book is selected.
- Switching accompaniment settings preserves completed speech fragments and annotations. Only the assembled mix is invalidated.
- Local model preparation and generation wait for another task to release its OS lock, with status messages, cancellation and a finite timeout. A process crash does not leave a stale lock.

Validation: 157 tests passed using the installed Python environment and Qt offscreen, with external network connections blocked. Local HTTP download fixtures and real subprocess lock-contention tests ran normally. Paid speech synthesis, model downloads and GPU inference are not part of that run. Existing data, voices, audio checkpoints and downloaded model weights are retained during an in-place update.
