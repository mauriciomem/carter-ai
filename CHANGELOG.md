# CHANGELOG

<!-- version list -->

## v0.16.1 (2026-10-25)

### Bug Fixes

- **config**: Validate policy.allowlist entries; restructure the user docs
  ([#41](https://github.com/mauriciomem/carter-ai/pull/41),
  [`4b240db`](https://github.com/mauriciomem/carter-ai/commit/4b240dbe5428eca31a0b697a432415f942bd65f9))

### Documentation

- Rewrite the README, add task-oriented guides, reference and contributing pages, restyle the evals
  README, remove superseded pages ([#41](https://github.com/mauriciomem/carter-ai/pull/41),
  [`4b240db`](https://github.com/mauriciomem/carter-ai/commit/4b240dbe5428eca31a0b697a432415f942bd65f9))


## v0.16.0 (2026-10-25)

### Refactoring

- Remove legacy harness support and migration code
  ([#40](https://github.com/mauriciomem/carter-ai/pull/40),
  [`4008f43`](https://github.com/mauriciomem/carter-ai/commit/4008f434d6b1d46057ba80a1a715a7ec567497a3))

### Breaking Changes

- Carter uninstall --legacy and the automatic migration from the old state directory are removed,
  and an older global AGENTS.md is no longer upgraded in place (anything other than the current
  rules text is kept as user-modified).


## v0.15.2 (2026-10-25)

### Bug Fixes

- Respect an existing opencode.jsonc and support carter ops --help
  ([#39](https://github.com/mauriciomem/carter-ai/pull/39),
  [`5932771`](https://github.com/mauriciomem/carter-ai/commit/5932771a74290d771effe0e5a3d792213006fa61))

- **install**: Respect an existing opencode.jsonc
  ([#39](https://github.com/mauriciomem/carter-ai/pull/39),
  [`5932771`](https://github.com/mauriciomem/carter-ai/commit/5932771a74290d771effe0e5a3d792213006fa61))


## v0.15.1 (2026-10-25)

### Bug Fixes

- **check**: Validate against fresh OpenCode agent data
  ([#37](https://github.com/mauriciomem/carter-ai/pull/37),
  [`a10fb8d`](https://github.com/mauriciomem/carter-ai/commit/a10fb8d8e315bcf9384b0f6f421f94c902570e48))


## v0.15.0 (2026-10-25)

### Chores

- Build, CI and .gitignore hygiene ([#35](https://github.com/mauriciomem/carter-ai/pull/35),
  [`0d108ae`](https://github.com/mauriciomem/carter-ai/commit/0d108aefa5f999d6df92e5338fec507ab88eb7c3))

### Continuous Integration

- Fix workflow comments, drop always-true guard, use find for agent count
  ([#35](https://github.com/mauriciomem/carter-ai/pull/35),
  [`0d108ae`](https://github.com/mauriciomem/carter-ai/commit/0d108aefa5f999d6df92e5338fec507ab88eb7c3))

### Documentation

- Accuracy pass after the OpenCode-only cleanup
  ([#34](https://github.com/mauriciomem/carter-ai/pull/34),
  [`adbb954`](https://github.com/mauriciomem/carter-ai/commit/adbb954f9aabf94bcba6a11f76baddbe31bfd9f9))

### Features

- **evals**: Price Claude 5.5 models from Anthropic's published rates
  ([#36](https://github.com/mauriciomem/carter-ai/pull/36),
  [`18fff08`](https://github.com/mauriciomem/carter-ai/commit/18fff08cfff4caf0671d0eb2c59f3e94dbf4321f))


## v0.14.1 (2026-10-25)

### Bug Fixes

- **install**: Count skill directories in the install summary
  ([#33](https://github.com/mauriciomem/carter-ai/pull/33),
  [`85ad82e`](https://github.com/mauriciomem/carter-ai/commit/85ad82e71a73294d6b40ebabedc303edb06d5a04))

- **install**: Count skills in the install summary; clean up tests and evals
  ([#33](https://github.com/mauriciomem/carter-ai/pull/33),
  [`85ad82e`](https://github.com/mauriciomem/carter-ai/commit/85ad82e71a73294d6b40ebabedc303edb06d5a04))


## v0.14.0 (2026-10-25)

### Refactoring

- Remove dead code and duplicates in the carter package, drop install --uninstall
  ([#32](https://github.com/mauriciomem/carter-ai/pull/32),
  [`152fe46`](https://github.com/mauriciomem/carter-ai/commit/152fe4658441a3b0d6faa386f09db18cf0884481))

- **install**: Remove dead code and deduplicate installer helpers
  ([#32](https://github.com/mauriciomem/carter-ai/pull/32),
  [`152fe46`](https://github.com/mauriciomem/carter-ai/commit/152fe4658441a3b0d6faa386f09db18cf0884481))


## v0.13.0 (2026-10-25)

### Bug Fixes

- **install**: Recognize every shipped global rules version so old installs upgrade
  ([#31](https://github.com/mauriciomem/carter-ai/pull/31),
  [`12575f3`](https://github.com/mauriciomem/carter-ai/commit/12575f34bb92e124b6d322d3a1aad0d02d1e21f0))

### Features

- **skills**: Retire carter-triage, upgrade old global rules and drop obsolete leftovers
  ([#31](https://github.com/mauriciomem/carter-ai/pull/31),
  [`12575f3`](https://github.com/mauriciomem/carter-ai/commit/12575f34bb92e124b6d322d3a1aad0d02d1e21f0))


## v0.12.0 (2026-10-25)

### Bug Fixes

- **policy**: Deny remote gh/vault commands to non-devops agents
  ([#30](https://github.com/mauriciomem/carter-ai/pull/30),
  [`da2d77e`](https://github.com/mauriciomem/carter-ai/commit/da2d77e66e7bb05fb1fa3666c2894f8c6528e427))

- **policy**: Deny remote gh/vault commands to non-devops agents and route ops: remote steps via
  devops ([#30](https://github.com/mauriciomem/carter-ai/pull/30),
  [`da2d77e`](https://github.com/mauriciomem/carter-ai/commit/da2d77e66e7bb05fb1fa3666c2894f8c6528e427))


## v0.11.1 (2026-10-25)

### Bug Fixes

- **uninstall**: Never delete user-edited or user-owned files
  ([#29](https://github.com/mauriciomem/carter-ai/pull/29),
  [`0b5328c`](https://github.com/mauriciomem/carter-ai/commit/0b5328c0e3b88bcb98929a6a9bc03ed64d843f3c))


## v0.11.0 (2026-10-25)

### Chores

- **docs**: Keep ADRs local-only and drop links to them
  ([#21](https://github.com/mauriciomem/carter-ai/pull/21),
  [`08bf3f7`](https://github.com/mauriciomem/carter-ai/commit/08bf3f74f128016144f9971f4d00d359a52f26f1))

### Features

- OpenCode is the only supported harness (min OpenCode 2.1)
  ([#28](https://github.com/mauriciomem/carter-ai/pull/28),
  [`bfadf83`](https://github.com/mauriciomem/carter-ai/commit/bfadf8396b8921473c6b0a5cde009cf6cfb22ebb))

### Breaking Changes

- Carter supports only OpenCode and requires OpenCode >= 2.1; the `target` config key and
  `--target` flag are gone; Carter state lives in ~/.carter.


## v0.10.0 (2026-10-24)

### Documentation

- Document the language and co-author rules
  ([#20](https://github.com/mauriciomem/carter-ai/pull/20),
  [`13044d3`](https://github.com/mauriciomem/carter-ai/commit/13044d3127e3b3f44d4e7c817f8b3bd1dde16e49))

### Features

- **config**: Docs_language for Carter internal documentation
  ([#20](https://github.com/mauriciomem/carter-ai/pull/20),
  [`13044d3`](https://github.com/mauriciomem/carter-ai/commit/13044d3127e3b3f44d4e7c817f8b3bd1dde16e49))

- **ops**: Credit the LLM as co-author instead of commit author
  ([#20](https://github.com/mauriciomem/carter-ai/pull/20),
  [`13044d3`](https://github.com/mauriciomem/carter-ai/commit/13044d3127e3b3f44d4e7c817f8b3bd1dde16e49))

- **templates**: English-only repository output and co-author rule
  ([#20](https://github.com/mauriciomem/carter-ai/pull/20),
  [`13044d3`](https://github.com/mauriciomem/carter-ai/commit/13044d3127e3b3f44d4e7c817f8b3bd1dde16e49))

### Breaking Changes

- **ops**: Carter no longer sets the commit author to the bot identity.


## v0.9.0 (2026-10-24)

### Bug Fixes

- **install**: Only remove the stale OpenCode instructions copy when Carter-owned
  ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

- **mcp**: Drop the third-party Atlassian bridge (supply-chain)
  ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

- **mcp**: Working server packages and valid OpenCode env syntax
  ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

- **ops**: Validate policy-override category
  ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

- **templates**: Remove dead branches and incorrect references
  ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

### Chores

- Remove legacy install shim and orphaned evals
  ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

- Remove stray file and fix .gitignore ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

- Review nitpicks ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

### Continuous Integration

- Bump GitHub Actions and Python matrix ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

- Drop unused setup-uv step and bump eval models
  ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

- Reproducible toolchain and green lint ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

### Documentation

- Align user docs with current code ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

- Remove historical RFCs and completed plans
  ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

- **adr**: Fix links to removed records and add status notes
  ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

- **changelog**: Backfill v0.8.0 entries dropped by PSR merge-commit bug
  ([`950e5ca`](https://github.com/mauriciomem/carter-ai/commit/950e5ca2541b98977cb9dfa8f1f0eacb8561abe1))

- **skills**: Current GitHub Actions versions in examples
  ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

### Features

- **models**: Bump to Claude 5.5 family ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

### Refactoring

- Remove dead and test-only code ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

- **ops**: Drop legacy --dry-run/--execute operations
  ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))

### Testing

- Legacy config keys survive update and check
  ([#19](https://github.com/mauriciomem/carter-ai/pull/19),
  [`eeaa864`](https://github.com/mauriciomem/carter-ai/commit/eeaa864292167bf4304171ccd82ab4e8c16a53ee))


## v0.8.0 (2026-08-01)

### Documentation

- Correct agent count and trim the carter-golang skill description
  ([`d603c26`](https://github.com/mauriciomem/carter-ai/commit/d603c26f66c138ebeadb643bbfe82c7fc14afdcd))

### Features

- **agents**: User-facing communication layer + static/template parity
  ([`ddfafbf`](https://github.com/mauriciomem/carter-ai/commit/ddfafbf9088d0635350941052b8c2191c3cf4158))


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

- **adr-0011**: Derive agent tools from policy so the agent chain keeps filesystem access
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

- **005**: P3 native subagent dispatch + fail-closed lint (step 4)
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
