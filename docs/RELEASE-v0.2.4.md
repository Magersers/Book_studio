# Book Studio v0.2.4

A book can apply gain to individual voices after speech loudness normalization. The optional book metadata field `voice_gain_db` maps avatar IDs to decibels; for example, `{"narrator-avatar-id": 2}` raises that narrator by 2 dB. Finite numeric values are limited to −12…+12 dB. Omitted voices and zero gain keep the existing assembly behavior. This field has no dedicated interface control in this release.

Gain applies to the selected speech clips during assembly and does not change sound effects or other voices. Lookahead limiting at four times the native sample rate constrains peaks, followed by a true-peak check against a −1 dB ceiling. Clips retain their exact frame count, so music and effect cue times are preserved. Limiting can reduce the measured boost in passages that already approach the ceiling.

Raw speech, cleanup reports, text, emotion tags and paid API cache identities remain unchanged. Changing only gain rebuilds derived audio from completed fragments without another speech request; gain processing is cached and checked by content hash. A nonzero gain changes the assembly cache identity, while default and zero-gain settings retain the previous identity.

Offline regression tests check a measurable 2 dB increase with sufficient headroom, true-peak limiting, exact frame count, unchanged source and cleanup files, voice-specific application, sound-effect exclusion and reuse of default and gain caches. Existing MP3 output remains 44.1 kHz stereo at 192 kb/s.
