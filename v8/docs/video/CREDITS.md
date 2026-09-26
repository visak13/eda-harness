# Credits and licences — the Heronry product video

## Music
- **Track:** "One Cool Minute" by Loyalty Freak Music, from the album *Minimal Ambient Bounce*.
- **Licence:** Creative Commons Zero 1.0 (CC0), a public-domain dedication. No attribution is required;
  this credit is a courtesy. Licence text: https://creativecommons.org/publicdomain/zero/1.0/
- **Source:** https://commons.wikimedia.org/wiki/File:Loyalty_Freak_Music_-_02_-_One_Cool_Minute.ogg
  (originally published on the Free Music Archive:
  https://freemusicarchive.org/music/Loyalty_Freak_Music/MINIMAL_AMBIENT_BOUNCE/Loyalty_Freak_Music_-_MINIMAL_AMBIENT_BOUNCE_-_02_One_Cool_Minute).
- **File:** `public/music/one-cool-minute.mp3` — the first 90 s of the original with a 5 s fade-out (85–90 s), re-encoded at 160 kbps
  (ffmpeg, re-encoded to MP3 160 kbit/s). Swap the track by replacing this file and `src/music.ts`.

## Remotion
The video is built with [Remotion](https://www.remotion.dev). Remotion is **not** under an open-source
licence: it is free for individuals and for companies of **3 or fewer people**; larger companies need a
Remotion company licence (https://www.remotion.dev/license). This folder is a documentation tool outside
every shipped Heronry package; forking the video at a larger company needs that licence.

## Fonts
- Nunito Sans (SIL Open Font Licence 1.1), via `@fontsource-variable/nunito-sans`.
- JetBrains Mono (SIL Open Font Licence 1.1), via `@fontsource/jetbrains-mono`.

## Art
- The Heronry logo (`public/brand/heronry-logo.png`) is the project's own brand asset
  (`v8/assets/brand/heronry/`).
- The seat avatars are drawn in code after the board's agent avatars (`web/src/components/agentAvatars.ts`).
- The chapter illustrations in `public/art/` were generated for this project with codex `image_gen`.
- Every board scene is a stylised mock with invented demo data; nothing is a screenshot.
