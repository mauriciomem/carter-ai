# CHANGELOG

<!-- version list -->

## v0.8.0 (2026-08-01)


## v0.7.0 (2026-08-01)

### Features

- **models**: Bump implementer tier from Sonnet 4.6 to Sonnet 5
  ([`44e8d24`](https://github.com/mauriciomem/carter-ai/commit/44e8d243cc73d1d777b44c4f9e3b8fed4f36feb1))


## v0.6.1 (2026-07-23)

### Bug Fixes

- **policy**: Move strictness-policy block off the wire into a comment
  ([#18](https://github.com/mauriciomem/carter-ai/pull/18),
  [`31b93c3`](https://github.com/mauriciomem/carter-ai/commit/31b93c38a156b8946a23a4a25d0460b87d1ac639))


## v0.6.0 (2026-07-15)

### Code Style

- **008**: Apply ruff format to test_skills.py
  ([#17](https://github.com/mauriciomem/carter-ai/pull/17),
  [`fece586`](https://github.com/mauriciomem/carter-ai/commit/fece586fd9081f61702cf35ad8478311da39b924))

### Features

- **008**: Deepen carter-golang into a curated multi-file skill set
  ([#17](https://github.com/mauriciomem/carter-ai/pull/17),
  [`fece586`](https://github.com/mauriciomem/carter-ai/commit/fece586fd9081f61702cf35ad8478311da39b924))


## v0.5.0 (2026-07-14)

### Features

- **003**: MCP server opt-in — install only selected servers
  ([`0894fd2`](https://github.com/mauriciomem/carter-ai/commit/0894fd206d89f34ada3b83fee9ce7df98425cba0))

- **003**: Official read-only Docker GitHub MCP server + docs (steps 2-6)
  ([`a8e76df`](https://github.com/mauriciomem/carter-ai/commit/a8e76dfbc528eca70065c3b0dc18cc005f8d6df1))


## v0.4.0 (2026-07-13)

### Bug Fixes

- **build**: Stop tracking carter/_data/ — it shadows the wheel force-include
  ([`2769c89`](https://github.com/mauriciomem/carter-ai/commit/2769c89a75c156abbdb20a2c346adf2f309bfd56))

### Code Style

- **007**: Apply ruff format to eval + test files
  ([`da7d4d4`](https://github.com/mauriciomem/carter-ai/commit/da7d4d47791829b903f7804ca610f71e2797fec8))

### Features

- **007**: Model-tier discipline — narrator+pm to Sonnet + profile knob
  ([`a21289c`](https://github.com/mauriciomem/carter-ai/commit/a21289c3b8f8591896ea4a212cad12c2f24204b5))

### Testing

- **install**: Update stale agent/skill counts (7→8, 23→28)
  ([`41ee8aa`](https://github.com/mauriciomem/carter-ai/commit/41ee8aa5b2b82777d1990a89c70544152dcdb648))


## v0.3.0 (2026-07-01)

### Chores

- Make source comments plan-agnostic (drop ADR/RFC/plan citations)
  ([`6334c19`](https://github.com/mauriciomem/carter-ai/commit/6334c196971e26c73aa5e2627e8107c10f87632b))

### Documentation

- Add ADR-0013, RFC-0006, withdraw RFC-0003
  ([`b8fd3a0`](https://github.com/mauriciomem/carter-ai/commit/b8fd3a041740eed807d058551c7a7aee2ba77fd8))

- Update frontmatter.md and README for 8th agent (M5)
  ([`30e38d4`](https://github.com/mauriciomem/carter-ai/commit/30e38d455dacde556ed923009d6605ba725e1ccb))

### Features

- Add 5-skill security bundle (M4)
  ([`1cd9e49`](https://github.com/mauriciomem/carter-ai/commit/1cd9e49d30c315e8a462c87997390864417fdd3e))

- Add boundary tests + per-agent roster rows (M3)
  ([`9f09da6`](https://github.com/mauriciomem/carter-ai/commit/9f09da67b517619ee314079201d61255a1b84231))

- Add carter-security as 8th first-class agent (M1+M2)
  ([`b319ed7`](https://github.com/mauriciomem/carter-ai/commit/b319ed739e58abd41d673612ffd86e5ca84c6ae1))


## v0.2.2 (2026-06-29)

### Bug Fixes

- **adr-0012**: Render OpenCode-shaped agents on install so the opencode CLI accepts them
  ([`c4fef37`](https://github.com/mauriciomem/carter-ai/commit/c4fef370038ddd396dfb7431ff73f15abbf7a1ef))

### Documentation

- **testing**: Document the editable-install carter/_data shadowing gotcha
  ([`94dc7ca`](https://github.com/mauriciomem/carter-ai/commit/94dc7ca638648100358b9efcd1116ea3e1e37a19))


## v0.2.1 (2026-06-28)

### Bug Fixes

- **adr-0011**: Derive VS Code tools: from policy so the agent chain keeps filesystem access
  ([`2521337`](https://github.com/mauriciomem/carter-ai/commit/25213373f6787e660b26261710a83b69511f6741))

### Documentation

- **plans**: Archive completed plan 005 + reconcile README to the refresh
  ([`ae2c3e6`](https://github.com/mauriciomem/carter-ai/commit/ae2c3e6ce5b39904f679fbbb54ec7c02cedf0b0a))


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
