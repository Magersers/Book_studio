# Book Studio v0.2.3

Final audiobook MP3s now use **44.1 kHz, stereo, 192 kb/s MPEG-1 Layer III** for both individual chapters and the whole book. The previous 24 kHz output used MPEG-2, where the encoder reduced the requested 192 kb/s to 160 kb/s; some resulting files produced MPG123 decoding warnings.

This change only affects the final MP3 encoding. Existing **24 kHz WAV speech fragments**, paid-response caches and checkpoints remain unchanged. Reassembling a book with the same text, voices and speech settings reuses those fragments and requires no new speech synthesis.

To replace an older MP3, run normal chapter/book rendering again using the saved fragments, then export the rebuilt result. Exporting an existing MP3 alone copies the file without re-encoding it.

The regression test uses real ffmpeg encoding and checks MPEG-1 headers, 192 kb/s, 44.1 kHz stereo output, decoding without warnings, duration preservation and reuse of completed speech on a second render. Internal chapter WAVs remain at 24 kHz. No live paid API requests are needed for the test.
