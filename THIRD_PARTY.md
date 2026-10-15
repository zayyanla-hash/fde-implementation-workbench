# Third-party assets

The application runs without npm installation or a frontend build. These third-party assets are included in the Python package and served locally under the existing self-only CSP.

| Asset | Use | License/source |
|---|---|---|
| Motion 14.2.0 | Word reveals, SVG path drawing, node springs, state-change feedback, section entrances | MIT; `src/workbench/static/Motion-LICENSE.txt`; [Motion docs](https://motion.dev/docs/quick-start); [pinned npm tarball](https://registry.npmjs.org/motion/-/motion-14.2.0.tgz) |
| Vengeance UI | Adapted corner-button frame and word-mask stagger pattern, rewritten for vanilla HTML/CSS/JS and this visual system | MIT; `src/workbench/static/Vengeance-LICENSE.txt`; [source at 2cf9379](https://github.com/Ashutoshx7/VengeanceUI/tree/2cf9379129a0167f0210cfd70a4fa4415c09f9e0) |
| Manrope variable font | Display and interface typography | SIL OFL 1.1; `src/workbench/static/Manrope-OFL.txt`; [Google Fonts source](https://github.com/google/fonts/tree/main/ofl/manrope) |

Motion is the unmodified `package/dist/motion.js` browser distribution. The downloaded npm archive's SHA-512 was verified against the registry integrity value before extracting only the bundle and license. No package installation scripts ran. File hashes are in `docs/ui-assets.json`.

Vengeance adaptations use transform-based corner lines/dots, keyboard `focus-within` support, the Workbench palette, static headline word wrappers, and a Motion-driven reveal. The original React/Tailwind components are not installed. Source patterns: [corner button](https://www.vengenceui.com/components/corner-button), [stagger text](https://www.vengenceui.com/components/stagger-text).

Skiper UI and Animmaster Lib were reviewed as design references only. No premium component source was copied. Their components are not dependencies.
