# CHANGELOG

<!-- version list -->

## v0.2.0 (2026-06-27)

### Chores

- **yui**: Remove all Yui system references and artifacts
  ([`5d67ec4`](https://github.com/mauriciomem/carter-ai/commit/5d67ec4df14d37bbb373abca46f1ef9629f4530e))

### Documentation

- Remove release badge (shields.io can't read a private repo)
  ([`debeaa7`](https://github.com/mauriciomem/carter-ai/commit/debeaa720eb873c67d77bb8b0cb48a0190e8df9b))

- **plans**: Archive completed plan 004 (pipeline, versioning & eval metrics)
  ([`32342c7`](https://github.com/mauriciomem/carter-ai/commit/32342c7deb10c610ed715fb35ad7f085331bf295))

### Features

- **005**: P0 staleness purge + time-awareness (step 1)
  ([`5aececf`](https://github.com/mauriciomem/carter-ai/commit/5aececfe5519f64a7afea7f9f9692fec8a35fd73))

- **005**: P1 two strictness levels, loose purged entirely (step 2)
  ([`d320613`](https://github.com/mauriciomem/carter-ai/commit/d3206134fdcb501cfdf119ed03e2ed88290fdbd4))

- **005**: P2 4-category taxonomy + first-class narrator + enforced redaction (step 3)
  ([`b437465`](https://github.com/mauriciomem/carter-ai/commit/b4374651de1ed0c4ddefa9a6f3904f5132aba847))

- **005**: P3 native subagent dispatch + fail-closed lint + /fleet rule (step 4)
  ([`0a2bc9b`](https://github.com/mauriciomem/carter-ai/commit/0a2bc9b4b3b0d08a770571dc6f4ac7735840e5a5))

- **005**: P4 per-agent model via models: block + name table + advisory (step 5)
  ([`d2543f6`](https://github.com/mauriciomem/carter-ai/commit/d2543f600c96e82b449c048dcb56a583e7fad6e0))

- **005**: P4-eval implementer-adherence eval + recorded fixture (step 6)
  ([`36cc97b`](https://github.com/mauriciomem/carter-ai/commit/36cc97b75cb2516d447257f51b46919a6e573d6b))


## v0.1.1 (2026-06-23)

### Bug Fixes

- **release**: Keep PSR pre-1.0 and stop changelog rendering Carter's templates/
  ([`5fa6773`](https://github.com/mauriciomem/carter-ai/commit/5fa6773eb69704f0bd55752a0ab6df198904c35b))

- **release**: Skip uv build in release job + add release badge to README
  ([`548649e`](https://github.com/mauriciomem/carter-ai/commit/548649e121240834dc137966ca00886bb2c00593))

### Continuous Integration

- Add PSR release pipeline + live-eval cron (plan 004 steps 5,10)
  ([`8b54e3e`](https://github.com/mauriciomem/carter-ai/commit/8b54e3e8724157fd3107db62ae3154c69cf6c848))

### Documentation

- Document the release flow + amend baseline tag to v0.1.0 (plan 004 step 6)
  ([`14a4439`](https://github.com/mauriciomem/carter-ai/commit/14a4439f379c34102f96730c7037f036e5dbafce))

### Refactoring

- **install**: Split installer.py into carter/install/ package (plan 004 step 8)
  ([`0cfbdea`](https://github.com/mauriciomem/carter-ai/commit/0cfbdea5fd0123981ad9c782493ebaa4d88470bb))


## v0.1.0 (2026-06-22)

- Initial Release
