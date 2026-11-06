# DeepSeek Harness (DSH) + RuleBase

Фреймворк поддерживает DSH как отдельный target установщика. Навыки ставятся в
`.dsh/skills/`, always-on правила генерируются в `.dsh/rules/` для плагина
[`github:mycodesite/dsh-rules`](https://github.com/mycodesite/dsh-rules), а
DSH-пресеты ролей — в `.dsh/presets.patch.yml`.

## Требования

- DSH ≥ 0.1.5-rc.1 (проверено на 0.2.1-rc.5).
- RuleBase (`github:mycodesite/dsh-rules`, проверено на 0.1.10).
- Python 3.9+ для установщика.

## Установка

1. Поставить RuleBase в профиль DSH (один раз на машину):

```bash
dsh plugin --profile web add github:mycodesite/dsh-rules#v0.1.10
```

> Не обновляйте RuleBase через маркет/npm: там есть одноимённый чужой пакет.
> Ставьте только GitHub-тег или tarball.

2. Из каталога фреймворка установить target `dsh` в проект:

```bash
python tools/install.py --ide dsh --all
# или выборочно:
python tools/install.py --ide dsh --include skill/coding-standards rule/framework-bootstrap
```

3. Запускать DSH через wrapper, чтобы применить проектные пресеты:

```powershell
.\dsh-1c.ps1
```

```bash
./dsh-1c.sh
```

Wrapper вызывает `dsh web --patch .dsh/presets.patch.yml`.

## Что создаётся

```text
<projectRoot>/
├── AGENTS.md                 # управляемый блок-карта (коммитится)
├── dsh-1c.ps1 / dsh-1c.sh    # запуск с --patch (коммитится)
└── .dsh/
    ├── .gitignore            # игнорирует ссылки и local.json
    ├── manifest.json         # хеши, профиль, компоненты (коммитится)
    ├── local.json            # абсолютные пути, машинное (не коммитится)
    ├── presets.patch.yml     # DSH-пресеты (коммитится)
    ├── skills/<name>/        # ссылки/junction на framework_eng/skills/...
    ├── rules/fw-*.md         # сгенерированные always-on правила (коммитятся)
    └── framework/            # on-demand правила, воркфлоу, субагенты, capabilities
```

`<projectRoot>` — ближайший предок с `.git`; без `.git` — выбранный `--project-dir`.
RuleBase читает правила из `<cwd>/.dsh/rules`, поэтому DSH нужно запускать из корня
проекта.

## Почему правила генерируются, а не симлинкуются

RuleBase 0.1.10 читает только плоские `*.md` и пропускает симлинки
(`RuleStore.list` проверяет `lstat().isSymbolicLink()`). Поэтому установщик
вырезает frontmatter/backmatter из `framework_eng/rules/<id>/SKILL.md` и пишет
реальные файлы `.dsh/rules/fw-*.md`. Их нужно коммитить: `--check` проверяет
актуальность в CI.

## Профили правил

- `parity` (по умолчанию) — все 41 always-on правило, ≈ 59 КиБ.
- `lite` — экспериментальный набор из 34 правил, ≈ 33 КиБ. Он **не** сохраняет
  поведение: часть исключённых правил содержит MUST/TRIGGER. Безопасный `lite`
  требует ретиринга тяжёлых правил; до этого используйте `parity`.

Переключение:

```bash
python tools/install.py --ide dsh --all --dsh-rules-profile lite
```

## DSH-пресеты

DSH не обнаруживает проектные пресеты автоматически: они объявляются в
композиции профиля. Установщик генерирует:

- `preset-1c-lead` — главная сессия (персона оркестратора + `allowedAgentPresets`);
- `1c-analyst`, `1c-architect`, `1c-developer-code`, `1c-developer-tests`,
  `1c-reviewer`, `1c-tester`, `1c-explorer`, `1c-debugger`,
  `1c-scenario-author`, `1c-scenario-coder`.

Патч также ставит `agent-preset-registry.default: 1c-lead` (отключается
`--dsh-keep-default-preset`). Шаблоны сняты с `standard.patch.yml` установленного
DSH; при обновлении DSH пресеты нужно перегенерировать (`--check` сообщит).

Если пресеты не загрузились, аварийный путь: прочитать
`.dsh/framework/subagents/<role>.md` и передать тело в `subagent` как prompt.

## Команды

```bash
python tools/install.py --ide dsh --check      # проверить правила/пресеты/AGENTS.md
python tools/install.py --ide dsh --doctor     # диагностика DSH/RuleBase/ссылок
python tools/install.py --ide dsh --uninstall  # удалить артефакты, сохранив пользовательские
python tools/install.py --ide dsh --sync       # синхронизировать состав по manifest
```

`--uninstall` удаляет только сгенерированные `fw-*.md`, ссылки, manifest,
presets и блок `AGENTS.md`; пользовательские `.dsh/rules/*.md`, не начинающиеся
с `fw-`, сохраняются.

## Миграция с ручной установки

Если использовались `~/.dsh/skills-1c/` и `customSkillDirs`:

1. Сделать backup `~/.dsh/profiles/web/cordis.patch.yml`.
2. Установить проектную версию.
3. Проверить, что проектные навыки перекрывают глобальные копии.
4. Удалить `customSkillDirs` на `skills-1c` и перезапустить DSH.
5. Удалить `~/.dsh/skills-1c/` после проверки.

## Ограничения и диагностика

- RuleBase инжектит правила в системный промпт **каждого** агента, включая
  сабагентов. `parity` — ≈ 59 КиБ на агента.
- Суммарный лимит RuleBase — 256 КиБ; установщик предупреждает после 200 КиБ и
  отказывает после 240 КиБ.
- `AGENTS.md` читается в начале сессии; после изменения нужна новая сессия.
- Пресеты и `--patch` применяются при запуске; после перегенерации нужен новый
  запуск через wrapper.
- На Windows без Developer Mode используются junction-каталоги; при их
  недоступности — копирование.

Если `--check` падает после обновления фреймворка — переустановите target `dsh`.
Если RuleBase не видит правила — проверьте, что DSH запущен из корня проекта и
что `.dsh/rules` содержит реальные файлы, а не симлинки.
