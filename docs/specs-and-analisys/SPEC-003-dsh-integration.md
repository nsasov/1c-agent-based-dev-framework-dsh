# SPEC-003: Интеграция фреймворка с DeepSeek Harness (DSH) и RuleBase

Status: Implemented (MVP)
Date: 2026-11-06
Author: AI-assisted planning (по запросу владельца фреймворка)
Reviewers: —

> Реализовано в MVP: target `dsh`, генерация always-on правил и манифеста,
> `AGENTS.md`, `.dsh/.gitignore`, DSH-пресеты и wrapper, тесты, документация.
> Осталось: runtime-smoke на живой DSH-сессии, опциональный ретиринг для `lite`,
> JS-шаблоны workflow и CI-прогон на GitHub.

---

## Context and problem statement

Фреймворк уже ставится в проекты через `tools/install.py` для Cursor, Claude Code,
Codex CLI, Windsurf, VS Code + Continue, RooCode, Kilo Code, Kiro, Antigravity и
«generic»-режима. Установка — это симлинки на `framework_eng/` (EN-зеркало), а не
копирование: один источник правды, обновление навыка сразу видно во всех проектах.

DeepSeek Harness (DSH) — новый харнес с другим контрактом:

- **Навыки.** DSH сканирует `<projectRoot>/.dsh/skills/<name>/SKILL.md` (rank 100),
  `<projectRoot>/.agents/skills` (rank 200), `customSkillDirs` (rank 300),
  `<dshHome>/skills` (rank 400), `<agentsHome>/skills` (rank 500). Каталог навыка —
  ровно один уровень; вложенные `**/SKILL.md` не находятся. Frontmatter обязан
  содержать `name` и `description`; `name` — kebab-case (`^[a-z0-9]+(?:-[a-z0-9]+)*$`).
  Неизвестные ключи (включая `alwaysApply`) игнорируются. Симлинки и junction-каталоги
  провайдер разворачивает через `stat`, то есть они работают.
- **Правила.** Плагин `github:mycodesite/dsh-rules` (RuleBase, проверено на 0.1.10)
  читает **плоские** `*.md` из `<dshHome>/rules` и `<cwd>/.dsh/rules`, сортирует по
  имени файла, полностью подставляет в системный промпт при каждом запросе всех
  агентов (включая сабагентов) и ограничивает суммарный объём 256 КиБ. Важно:
  `RuleStore.list()` использует `lstat()` и **пропускает симлинки**; вложенные
  каталоги не сканируются. Метаданных `alwaysApply`/`globs` у RuleBase нет.
- **Инструкции.** `dsh-agent-instructions` подхватывает `AGENTS.md`/`CLAUDE.md`
  по цепочке от корня проекта (ближайший `.git`) до cwd; бюджет по умолчанию 64 КиБ;
  `@`-импортов, как в Claude Code, нет.
- **Сабагенты.** DSH даёт инструмент `subagent`, но не сканирует проектные
  определения агентов. Кастомные роли — это `agent-preset` + `persona` в профиле
  DSH (Cordis YAML), то есть глобальная конфигурация, а не файлы проекта.
- **Воркфлоу.** DSH-инструмент `workflow` исполняет JS-сценарий; файлового
  обнаружения воркфлоу, аналогичного skills, нет.

Сейчас DSH-интеграция существует только «ручным» способом: в
`C:\Users\Prog1\.dsh\skills-1c\` лежат копии навыков, а в
`~/.dsh/profiles/web/cordis.patch.yml` прописаны `customSkillDirs` на категории.
Это не воспроизводимо, не версионируется, не содержит правил и расходится с
`framework_eng/`. Нужен штатный target `dsh` в установщике.

### Измеренное состояние (2026-11-06)

| Показатель | Значение |
|---|---|
| Компонентов с `SKILL.md` | 149: 100 навыков, 45 правил, 4 воркфлоу |
| Правила `alwaysApply: true` | 41 |
| Правила `alwaysApply: false` | 4 (`codex-subagent-orchestration`, `cross-provider-review`, `herdr-agent-routing`, `yaxunit-isolation`) |
| EN-тела always-on правил (без frontmatter/backmatter) | ≈ 59,2 КиБ (60 607 Б; ≈ 17 тыс. токенов) |
| Сабагенты | 11 ролей + шаблон |
| Коллизии имён rule ↔ skill | 18 пар (`coding-standards`, `git-workflow`, `source-of-truth`, …) |
| Коллизии skill ↔ workflow | 1 (`quick-fix`) |
| Фантомные компоненты | 3: `skill/analyst`, `skill/architect`, `skill/reviewer` из `references/fallback-standalone.md` |

Фантомы возникают потому, что `FrameworkGraph._scan()` обходит `rglob("*.md")` и
принимает любой файл с frontmatter за компонент; DSH такие «навыки» не увидит,
но установщик создаст мусорные цели.

### Проблема

Без отдельного DSH-target:

1. Навыки приходится копировать руками; копии стареют, EN-зеркало не используется.
2. Правила не работают: RuleBase не читает каталоги с `SKILL.md` и не следует симлинкам.
3. `AGENTS.md` не создаётся; DSH не знает про фреймворк, если RuleBase не установлен.
4. Сабагенты и воркфлоу недостижимы: DSH не обнаруживает их файлы.
5. Нет тестов, документации и предсказуемой деинсталляции.

---

## Requirements (RFC 2119)

### MUST

1. `tools/install.py` MUST поддерживать `--ide dsh` как полноценный target с
   отображением в интерактивном списке, `--list`, `--dry-run`, `--sync` и `--copy`.
2. Установщик MUST ставить навыки в `<dshProjectRoot>/.dsh/skills/<short_name>/`
   так, чтобы DSH находил `<short_name>/SKILL.md`; источник — `framework_eng/skills/...`
   (EN), с fallback на RU только при отсутствии EN-файла.
3. Установщик MUST генерировать always-on правила в `<dshProjectRoot>/.dsh/rules/fw-*.md`
   как **обычные файлы** (не симлинки), очищенные от frontmatter и технического
   backmatter; суммарный объём — не более 256 КиБ (жёсткий предел RuleBase).
4. В `.dsh/rules` MUST попадать только правила с `alwaysApply: true`; on-demand
   правила MUST оставаться доступными по пути `.dsh/framework/rules/<name>/SKILL.md`,
   но MUST NOT инжектиться RuleBase.
5. On-demand правила, воркфлоу и субагенты MUST быть доступны агенту по стабильным
   путям внутри `.dsh/framework/`; в `AGENTS.md` MUST быть указано правило
   перенаправления `framework/...` → `.dsh/framework/...`.
6. Установщик MUST идемпотентно создавать/обновлять управляемый блок в
   `<projectRoot>/AGENTS.md` (маркеры начала/конца), не затирая пользовательский
   текст; размер блока — не более 2 КиБ; при удалении MUST удаляться только блок.
7. Установщик MUST быть идемпотентным: повторный запуск не создаёт дублей, не
   ломает пользовательские файлы, а `--dry-run` не делает ни одной записи.
8. Деинсталляция MUST удалять только артефакты фреймворка (сгенерированные
   `fw-*.md`, ссылки, манифест, блок `AGENTS.md`) и MUST сохранять пользовательские
   правила/навыки/файлы.
9. `FrameworkGraph._scan()` MUST NOT принимать за компоненты файлы из
   `skills/**/references/**`, `assets/**`, `scripts/**` и любые `.md`, кроме
   `SKILL.md` (для навыков/правил/воркфлоу) и `subagents/*.md`.
10. Для DSH MUST быть тесты: unit-тесты генератора/установщика и интеграционный
    тест во временном проекте; MUST проверяться Windows и Linux.
11. Документация MUST описывать установку, пути, ограничения RuleBase, миграцию с
    `~/.dsh/skills-1c` и диагностику.
12. Установщик MUST генерировать проектный `.dsh/presets.patch.yml` с DSH-пресетами
    для ролей и wrapper-скрипт запуска; генерация MUST быть идемпотентной и
    проверяемой, пресеты MUST использовать EN-тела ролей и не дублировать правила.
    Пресеты — launch-level механизм DSH; проектный патч подключается через
    `--patch`, глобальное слияние — только явным opt-in.

### SHOULD

13. `parity` SHOULD быть профилем по умолчанию: все always-on правила (≈ 59 КиБ).
    `lite` (курируемый набор, ≈ 33 КиБ) SHOULD оставаться экспериментальным
    режимом до ретиринга тяжёлых правил; выбор — `--dsh-rules-profile`.
14. `--check` SHOULD проверять актуальность сгенерированных правил по хешам и
    сообщать о расхождениях без записи.
15. `--doctor` SHOULD проверять: версию DSH, наличие RuleBase в профиле, корень
    проекта, целостность ссылок, объём правил, наличие блока `AGENTS.md`,
    дублирование глобальных `customSkillDirs`, актуальность пресетов.
16. Сгенерированные `fw-*.md` SHOULD иметь явный признак generated (`fw-`-префикс,
    запись в манифесте) и проверяться `--check`. Read-only MAY использоваться
    только в локальном режиме без коммита: для закоммиченных файлов он мешает
    `git pull`/merge.
17. Установщик SHOULD использовать junction-каталоги на Windows, если symlink
    недоступен (Developer Mode выключен), вместо копирования всего каталога навыка.

### MAY

18. MAY добавить JS-шаблоны DSH `workflow` для `full-cycle`/`quick-fix` как
    альтернативу чтению Markdown-воркфлоу.
19. MAY подготовить upstream-PR в `dsh-rules` на поддержку симлинков внутри
    каталога правил (с проверкой, что ссылка не выходит за пределы каталога).
20. MAY поддерживать явный opt-in `--install-rulebase` для установки/пиннинга
    `github:mycodesite/dsh-rules` в указанный профиль DSH; без флага установщик
    только проверяет наличие плагина и печатает команду.

### MUST NOT

21. MUST NOT класть в `.dsh/rules` симлинки: RuleBase 0.1.10 их пропускает.
22. MUST NOT инжектить on-demand правила в `.dsh/rules`: это ломает семантику
    «ленивой загрузки» и раздувает контекст.
23. MUST NOT автоматически править `~/.dsh/profiles/*/cordis.patch.yml` или
    `customSkillDirs` без явного opt-in: это глобальное состояние пользователя.
24. MUST NOT использовать RU-версию правила, если существует EN-зеркало
    (кроме явного `--lang ru`).
25. MUST NOT полагаться на `@`-импорты в `AGENTS.md`: DSH их не поддерживает.
26. Ссылки `.dsh/skills`, `.dsh/framework` и машинный `.dsh/local.json` MUST NOT
    коммититься. Сгенерированные `fw-*.md`, `AGENTS.md`, `.dsh/.gitignore` и
    портируемый `manifest.json` коммитятся (решение проекта от 2026-11-06).

---

## Boundaries

### In scope

- Target `dsh` в `tools/install.py`: пути, установка, удаление, синхронизация.
- Генератор `.dsh/rules/fw-*.md` и портируемый манифест.
- Управляемый блок `AGENTS.md`.
- Раскладка `.dsh/framework` для on-demand правил, воркфлоу и субагентов.
- Генератор DSH-пресетов `.dsh/presets.patch.yml` и wrapper запуска.
- Политика коммита: правила/AGENTS.md/manifest — в git, ссылки/локальное — нет.
- Исправление сканирования компонентов (фантомные навыки).
- Тесты, документация, миграция, диагностика.

### Out of scope

- Изменение кода RuleBase (кроме возможного upstream-PR, см. MAY 19).
- Установка и настройка MCP-серверов (это отдельный слой; DSH использует
  `dsh-mcp-client`, конфигурация — в профиле DSH).
- Полный перенос JS-движка воркфлоу; автоматическое слияние пресетов в
  глобальный профиль без явного opt-in.
- GUI-тесты Vanessa, 1С-база, метаданные — в этой задаче не участвуют.
- Поддержка DSH-версий ниже 0.1.5-rc.1 (минимальная версия RuleBase 0.1.4+).

---

## Considered options

### Вариант A. Оставить ручную копию (status quo)

Плюсы: ничего не делать. Минусы: дрейф, нет правил, нет воспроизводимости,
невозможно поддерживать несколько проектов. Отклонён.

### Вариант B. Глобальная установка в `~/.dsh/skills` и `~/.dsh/rules`

Плюсы: один раз поставил — работает во всех проектах. Минусы: 1С-правила
начинают действовать в не-1С проектах; RuleBase инжектит их всегда; обновление
фреймворка меняет поведение всех сессий; нет проектной изоляции. Отклонён как
основной режим (может остаться opt-in для личных машин).

### Вариант C. Установщик-адаптер + генерация файлов (рекомендуется)

Плюсы: работает со штатным RuleBase без форка; проект изолирован; установка
воспроизводима; можно проверить и откатить. Минусы: правила — копии, а не
симлинки, поэтому нужен `--check` и дисциплина переустановки; 59 КиБ always-on
инжектятся в каждый запрос (включая сабагентов).

### Вариант D. Отдельный DSH-плагин `dsh-1c-framework`

Плагин читает checkout фреймворка, сам регистрирует провайдер навыков и
динамически формирует правила под проект (с проверкой маркера `.dsh`), не создавая
копий. Плюсы: лучший UX, нет дрейфа, можно фильтровать по агенту/проекту.
Минусы: TypeScript/Cordis-разработка, публикация, версионирование, зависимость
от внутренних API DSH; для первого шага избыточно. Отложен как стратегическое
направление.

### Вариант E. Симлинки на правила

Технически невозможен с RuleBase 0.1.10: `RuleStore.list()` отбрасывает
`st.isSymbolicLink()`. Если upstream примет PR — можно вернуться к SSOT-модели.

---

## Chosen solution

**Вариант C** как MVP, с архитектурной совместимостью с вариантом D:

1. Проектная установка в `<dshProjectRoot>/.dsh/`.
2. Навыки — ссылки/копии каталогов в `.dsh/skills/` (DSH их видит).
3. Always-on правила — **сгенерированные реальные файлы** `.dsh/rules/fw-*.md`
   из EN-зеркала, без frontmatter/backmatter.
4. On-demand правила, воркфлоу, субагенты, capabilities — ссылки/копии в
   `.dsh/framework/`; агент читает их по требованию.
5. `AGENTS.md` — короткий управляемый блок-карта, без дублирования правил.
6. Манифест `.dsh/manifest.json` — портируемый источник истины для `--check`,
   `--sync`, деинсталляции и диагностики; машинный `.dsh/local.json` — отдельно.
7. DSH-пресеты — `.dsh/presets.patch.yml` + wrapper `dsh-1c.ps1`/`dsh-1c.sh`;
   пресеты launch-level, подключаются через `--patch`.
8. Политика коммита: `fw-*.md`, `AGENTS.md`, `.dsh/.gitignore`, портируемый
   `manifest.json`, `presets.patch.yml` и wrapper коммитятся; ссылки
   `.dsh/skills`, `.dsh/framework` и `.dsh/local.json` — нет.

Обоснование: это единственный вариант, который работает со штатным RuleBase,
не меняет глобальный профиль DSH и сохраняет модульность фреймворка. Плата —
генерация копий правил; она компенсируется манифестом, `--check` и повторной
установкой.

Последствия:

- Появляется новый класс артефактов — сгенерированные правила; их нельзя
  редактировать руками, они перезаписываются. Но они коммитятся, поэтому
  обновление фреймворка видно в diff и проходит review.
- `AGENTS.md` становится точкой входа DSH; его нужно коммитить (пользовательский
  текст сохраняется).
- Пресеты не обнаруживаются DSH автоматически: проектный патч нужно передать
  при запуске (`dsh web --patch .dsh/presets.patch.yml`); wrapper это инкапсулирует.
- На Windows требуется junction-fallback, иначе копирование навыков ухудшит
  обновляемость.

---

## Technical design

### 1. Целевая раскладка

```text
<projectRoot>/                     # ближайший .git или выбранный каталог
├── AGENTS.md                      # управляемый блок (коммитится)
├── dsh-1c.ps1 / dsh-1c.sh         # wrapper запуска с --patch (коммитится)
└── .dsh/
    ├── .gitignore                 # игнорирует только ссылки/локальное (коммитится)
    ├── manifest.json              # хеши, профиль, компоненты (коммитится, портируемый)
    ├── local.json                 # абсолютный путь checkout, машинное (gitignore)
    ├── presets.patch.yml          # DSH-пресеты (коммитится)
    ├── skills/                    # ссылки/копии каталогов навыков (gitignore)
    ├── rules/
    │   ├── fw-000-framework-bootstrap.md   # сгенерировано (коммитится)
    │   ├── fw-010-coding-standards.md      # сгенерировано (коммитится)
    │   └── team-conventions.md             # пользовательское (коммитится)
    └── framework/                 # ссылки/копии reference-документов (gitignore)
        ├── rules/<name>/SKILL.md
        ├── workflows/<name>/SKILL.md
        ├── subagents/<role>.md
        └── capabilities/
```

`.dsh` целиком **не** игнорируется: коммитятся правила, AGENTS.md, manifest,
пресеты и gitignore. Игнорируются только машинно-зависимые ссылки и локальный
путь checkout.

`<projectRoot>` для DSH — ближайший предок с `.git` (контракт
`dsh-skill-filesystem`); если `.git` нет — выбранный каталог проекта. Это
отличается от остальных IDE, где установка идёт в выбранный `--project-dir`.
Установщик MUST предупредить, если `--project-dir` не совпадает с DSH-корнем.

### 2. Изменения в `tools/install.py`

Добавить target:

```python
"dsh": {
    "name": "DeepSeek Harness (DSH)",
    "rules_dir": ".dsh/rules",
    "rules_ext": ".md",
    "skills_dir": ".dsh/skills",
    "reference_dir": ".dsh/framework",
    "agents_dir": ".dsh/framework/subagents",
    "workflows_dir": ".dsh/framework/workflows",
    "rule_mode": "rulebase",          # правила не раскладываются по одному
    "entrypoint": "AGENTS.md",
    "presets_file": ".dsh/presets.patch.yml",
    "launcher": "dsh-1c",
    "manifest": ".dsh/manifest.json",
    "local_state": ".dsh/local.json",
    "description": "DSH + RuleBase: навыки в .dsh/skills/, always-on правила генерируются в .dsh/rules/, пресеты — в .dsh/presets.patch.yml",
}
```

Ключевые функции:

| Функция | Изменение |
|---|---|
| `FrameworkGraph._scan()` | принимать только `SKILL.md` для skill/rule/workflow; `subagents/*.md` — для субагентов; исключить `references/`, `assets/`, `scripts/` |
| `_component_target_file()` | ветка `dsh`: skill → `.dsh/skills/<short_name>`; rule/workflow → `.dsh/framework/...`; subagent → `.dsh/framework/subagents/<short_name>.md` |
| `install_components()` | для `rule_mode == "rulebase"` не создавать файл правила; собрать `selected_rule_ids` и после цикла вызвать генератор |
| `_create_dir_link()` | новая helper-функция: symlink → junction (Windows) → copy |
| `detect_existing_component_symlinks()` | для DSH дополнительно читать `.dsh/manifest.json` |
| `install_components()` (remove) | удалять только артефакты из манифеста; пользовательские файлы не трогать |
| `write_session_log()` | добавить `dsh`-блок: профиль, язык, сгенерированные файлы, хеши |
| `print_rules_import_hint()` | для DSH не печатать @-импорты; печатать путь к `.dsh/rules` и команду проверки |
| `estimate_context_usage()` | для DSH считать сгенерированные тела правил + каталог навыков |
| `dsh_presets.py` | новый модуль: генерация `.dsh/presets.patch.yml` и wrapper |
| `--doctor` | новый режим проверки, включая актуальность пресетов |

Важно: `detect_symlink_support()` проверяет **файловый** симлинк. На Windows без
Developer Mode он вернёт `False`, но junction-каталоги при этом доступны. Поэтому
для DSH helper `_create_dir_link()` должен пробовать junction независимо от
глобального `use_symlinks`; флаг `--copy` — явный запрет любых ссылок.

Новые CLI-флаги:

```text
--ide dsh
--dsh-rules-profile parity|lite
--dsh-lang en|ru
--dsh-no-agents-md
--dsh-presets
--dsh-install-presets-profile
--dsh-keep-default-preset
--install-rulebase
--check
--uninstall
--doctor
```

`--uninstall` для MVP можно ограничить DSH: удалить сгенерированные правила,
ссылки, манифест и блок `AGENTS.md`, сохранив пользовательские `.md` в
`.dsh/rules` и пользовательские навыки.

### 3. Генератор правил `tools/dsh_rules.py`

Отдельный модуль, импортируемый установщиком и пригодный для CI.

```text
python tools/dsh_rules.py render \
  --framework-dir framework \
  --mirror-dir framework_eng \
  --project-dir . \
  --profile parity \
  --lang en

python tools/dsh_rules.py check --project-dir .
python tools/dsh_rules.py clean --project-dir .
```

Алгоритм `render`:

1. Загрузить компоненты через `FrameworkGraph` (или общий парсер).
2. Отобрать `type == "rule"` и `always_apply == True`; для профиля `lite` —
   только ID из `tools/dsh-rules.yaml`.
3. Для каждого правила взять EN-файл `framework_eng/rules/<id>/SKILL.md`; если
   его нет — RU с предупреждением.
4. Разобрать frontmatter, взять `name`/`description`; тело — после frontmatter.
5. Удалить терминальный backmatter `--- depends_on: ... ---` и ранний
   технический блок (как `parse_frontmatter`/`_terminal_backmatter`).
6. Обеспечить H1: если тело не начинается с `# `, добавить `# <display_name>`.
7. Записать `.dsh/rules/fw-<order>-<id>.md` как обычный файл; `order` — из
   `tools/dsh-rules.yaml` (bootstrap = 000), иначе 100 + алфавитный порядок.
8. Удалить устаревшие `fw-*.md`, которых нет в новом наборе (только по манифесту).
   Если файлы были закоммичены, удаление попадёт в diff — это ожидаемо.
9. Посчитать `sum(len(body.encode("utf-8")))`; предупредить при > 200 КиБ,
   отказать при > 240 КиБ.
10. Записать `.dsh/manifest.json` (портируемый, коммитится) и `.dsh/local.json`
    (абсолютный путь checkout, машинный, gitignore):
    ```json
    {
      "generator": "1c-agent-framework",
      "version": "0.4.1",
      "dsh": {
        "profile": "parity",
        "lang": "en",
        "rules": [
          {"id": "framework-bootstrap", "file": "fw-000-framework-bootstrap.md",
           "source": "framework_eng/rules/framework-bootstrap/SKILL.md",
           "sha256": "..."}
        ],
        "total_bytes": 60607,
        "components": ["rule/framework-bootstrap", "skill/coding-standards", "..."],
        "presets": {
          "file": "presets.patch.yml",
          "dsh_version": "0.2.1-rc.5",
          "template_sha256": "..."
        }
      }
    }
    ```

`manifest.json` не содержит абсолютных путей и пригоден для CI. `local.json`
хранит `framework_root`, timestamp и прочие машинные данные; он не коммитится.
`--check` на CI получает путь к checkout через `--framework-dir` или env.

`check` сравнивает хеши исходных файлов и содержимое целей; при расхождении печатает
список и возвращает код 1. `clean` удаляет только `fw-*.md` и манифест (с
предупреждением, что они могут быть в git), не трогая пользовательские правила.

**Профили `parity` и `lite`.** Разница — только в наборе always-on правил,
попадающих в `.dsh/rules`. Навыки, on-demand правила, воркфлоу и субагенты
устанавливаются одинаково; `lite` ничего не удаляет из `.dsh/framework`, а лишь
перестаёт инжектить часть правил в системный промпт.

| | `parity` | `lite` (стартовый кандидат) |
|---|---|---|
| Always-on правил | 41 | 34 |
| Объём EN-тел | 60 607 Б (59,2 КиБ) | 33 905 Б (33,1 КиБ) |
| Что инжектится | все `alwaysApply: true` | 31 правило ≤ 2 КиБ + `framework-bootstrap`, `no-manual-xml-edit`, `capability-resolution` |
| Экономия на запрос/агента | — | ≈ 26,1 КиБ (≈ 7,5 тыс. токенов) |
| Совместимость поведения | соответствует текущим IDE | **не behaviour-preserving** |
| Основной риск | больше контекста | MUST-текст исключённых правил не виден всегда |

Исключённые в `lite` (кандидат):

| Правило | Байт | Почему в кандидате на исключение | Риск |
|---|---:|---|---|
| `test-zero-residue` | 8 311 | тяжёлая процедура очистки тестов | содержит MUST-инвариант; нужен сплит «триггер + тело» |
| `vanessa-scenario-policy` | 4 401 | большой how-to по Vanessa | содержит MUST-политику; вероятно, оставить |
| `skill-learning-policy` | 3 767 | процедура чтения/записи lessons | содержит TRIGGER/MUST; вероятно, оставить |
| `semantic-code-comments` | 2 818 | в основном SHOULD-практика | низкий; можно читать по требованию |
| `report-discovered-issues` | 2 648 | процедура отчёта о побочных дефектах | MUST «сообщать после задачи»; вероятно, оставить |
| `predefined-elements` | 2 512 | how-to поиска предопределённых значений | MUST «искать до создания»; вероятно, оставить |
| `tdd-policy` | 2 245 | описание слоёв TDD | MUST Red → Green; вероятно, оставить |

Вывод: `parity` — безопасный дефолт. `lite` как **чистый фильтр** — это
эксперимент по экономии контекста, а не эквивалент поведения: семь исключённых
документов содержат не только how-to, но и MUST/TRIGGER. Чтобы `lite` стал
безопасным, нужен ретиринг контента: каждое тяжёлое правило разбивается на
короткий always-on триггер и подробное on-demand тело (направление уже
зафиксировано в `docs/rules-skills-retiering/manifest.md`). До этого `lite`
включается только явным флагом и проверяется на реальной сессии.

### 4. `AGENTS.md`

Управляемый блок (английский, чтобы не платить за кириллицу):

```markdown
<!-- BEGIN 1c-agent-framework (managed) -->
## 1C Agent Development Framework on DSH

Always-on rules are injected by the RuleBase plugin from `.dsh/rules/`.
Do not edit `fw-*.md`; put project rules in other `.md` files there.

- Skills: `.dsh/skills/` (discovered by DSH).
- Reference docs: `.dsh/framework/`. Where framework text says `framework/...`,
  resolve it under `.dsh/framework/...`.
- On-demand rules: `.dsh/framework/rules/<id>/SKILL.md`.
- Workflows: `.dsh/framework/workflows/<id>/SKILL.md`.
- Subagents: `.dsh/framework/subagents/<role>.md`. Prefer the generated
  `1c-<role>` preset via `subagent(agent_preset=...)`; if presets are unavailable,
  pass the role body as the prompt. Keep the orchestrator in the main session
  (DSH maxDepth = 1).
- Presets: `.dsh/presets.patch.yml`; start DSH via `dsh-1c.ps1`/`dsh-1c.sh`
  so the project patch is applied. The lead preset is `1c-lead`.
- Capabilities: `capabilities/registry.yaml`.
- If the `framework-bootstrap` rule is missing from the rule library, read
  `.dsh/framework/rules/framework-bootstrap/SKILL.md` before acting.
<!-- END 1c-agent-framework -->
```

Правила записи:

- Если `AGENTS.md` нет — создать с блоком.
- Если есть — заменить блок между маркерами, сохранив остальное.
- Если маркеров нет — дописать блок в конец (после пустой строки).
- При `--uninstall` — удалить только блок; если файл стал пустым, оставить
  пустой файл (не удалять пользовательский путь).
- `--dsh-no-agents-md` отключает создание/обновление.

### 5. `.dsh/.gitignore` и манифест

Установщик создаёт `.dsh/.gitignore` (если нет) с паттернами:

```gitignore
# Installed links and machine-local state (do not commit)
/skills/
/framework
/local.json
```

Если файл уже есть — добавить управляемый блок с маркерами, не затирая
пользовательские правила. Коммитятся: `.dsh/rules/*.md` (включая `fw-*`),
`.dsh/manifest.json`, `.dsh/presets.patch.yml`, `.dsh/.gitignore`, `AGENTS.md`
и wrapper. Не коммитятся: `.dsh/skills/`, `.dsh/framework`, `.dsh/local.json`.
`--check` в CI проверяет, что закоммиченные `fw-*.md` соответствуют checkout.
В самом репозитории фреймворка добавить в корневой `.gitignore` только
`.dsh/skills/`, `.dsh/framework`, `.dsh/local.json` — не весь `.dsh/`, иначе
нельзя будет коммитить правила.

### 6. Раскладка компонентов

| Тип | Цель | Механизм | RuleBase |
|---|---|---|---|
| `skill` | `.dsh/skills/<short_name>` → каталог навыка | symlink/junction/copy | обнаруживается DSH |
| `rule` c `alwaysApply: true` | `.dsh/rules/fw-<order>-<id>.md` + справочная ссылка `.dsh/framework/rules/<short_name>/SKILL.md` | сгенерированный файл + ссылка/копия | инжектится из `.dsh/rules` |
| `rule` c `alwaysApply: false` | `.dsh/framework/rules/<short_name>/SKILL.md` | ссылка/копия | не инжектится, читается по требованию |
| `workflow` | `.dsh/framework/workflows/<short_name>/SKILL.md` | ссылка/копия | справочный документ |
| `subagent`/`agent` | `.dsh/framework/subagents/<short_name>.md` | ссылка/копия | справочный документ |
| `capabilities` | `.dsh/framework/capabilities` → EN-зеркало | ссылка/копия | справочный документ |

Коллизии rule ↔ skill не возникают, потому что on-demand правила не попадают
в `.dsh/skills`. Коллизия `quick-fix` skill ↔ workflow решается размещением
workflow в `.dsh/framework/workflows/quick-fix`, а не в каталоге навыков.

### 7. Сабагенты, DSH-пресеты и воркфлоу

Субагенты устанавливаются как справочные `.md` в `.dsh/framework/subagents/`, но
в MVP дополнительно генерируются DSH-пресеты — решение проекта от 2026-11-06.

**Почему пресеты — launch-level.** DSH не сканирует проектные определения
агентов: пресеты объявляются как `@deepseek-ai/dsh-agent-preset` в композиции
профиля. Проектный патч `.dsh/presets.patch.yml` подключается только через
`--patch` при запуске; wrapper инкапсулирует это. Глобальное слияние в
`~/.dsh/profiles/<profile>/cordis.patch.yml` — только явный opt-in
(`--dsh-install-presets-profile`) с backup и управляемым блоком.

**Генератор `tools/dsh-presets.py`.**

1. Проверяет версию DSH и сверяет набор plugin-id в установленном
   `@deepseek-ai/dsh-web-app/presets/standard.patch.yml` с шаблонами
   `tools/dsh-presets-lead.yml.tmpl` / `tools/dsh-presets-role.yml.tmpl`
   (override — `--dsh-standard-preset`).
2. Использует шаблоны, а не парсинг/переэмиссию YAML: в `standard.patch.yml`
   есть теги `!!js` и `cordis:group`, которые обычный YAML-парсер не сохранит.
   Шаблоны — текстовая копия композиции с плейсхолдерами
   `{{PRESET_ID}}`, `{{PERSONA_PREFIX}}`, `{{ALLOWED_PRESETS}}`, `{{ORDER}}`.
3. Для каждой роли (analyst, architect, developer-code, developer-tests,
   reviewer, tester, explorer, debugger, scenario-author, scenario-coder):
   - читает `framework_eng/subagents/<role>.md`, срезает frontmatter/backmatter;
   - берёт role-шаблон, подставляет persona и id `1c-<role>`, `name`, `order`;
   - в role-шаблоне delegation-группа отсутствует: сабагент не спавнит детей.
4. Генерирует `preset-1c-lead` из lead-шаблона: persona оркестратора +
   `tool-subagent.allowedAgentPresets` со всеми `1c-<role>`. В патч добавляется
   `agent-preset-registry.default: 1c-lead`, чтобы главная сессия стартовала
   в роли Lead (можно отключить флагом `--dsh-keep-default-preset`).
5. Пишет `.dsh/presets.patch.yml` (`- insert: [...]`), wrapper
   `dsh-1c.ps1`/`dsh-1c.sh` (`dsh web --patch .dsh/presets.patch.yml "$@"`).
6. `--check` сравнивает версию DSH и хеш шаблонов; при обновлении DSH шаблоны
   нужно сверить и перегенерировать пресеты.

**Обязательный spike перед реализацией.** Проверить на установленном DSH:

- что шаблонная композиция (lead/role) действительно даёт роли инструменты и
  skill-filesystem;
- что `allowedAgentPresets` на `tool-subagent` виден модели и выбор пресета
  работает при `subagent(...)`;
- что дочерний пресет без delegation-группы не может спавнить детей;
- что `--patch .dsh/presets.patch.yml` не конфликтует с профилем и HMR.

Если шаблоны разойдутся с `standard.patch.yml`, fallback — генерация через
PyYAML с кастомным конструктором `!!js` (сохранять тег при переэмиссии) и
отдельная проверка plugin-id. Если пресеты не загрузились, оркестратор читает
`.dsh/framework/subagents/<role>.md` и передаёт тело в `subagent` как prompt —
этот путь сохраняется как аварийный.

Воркфлоу остаются Markdown-документами; JS-шаблоны `workflow` — MAY 18.

### 8. Контекстный бюджет

- Always-on правила: ≈ 59 КиБ EN в профиле `parity`; ≈ 30–35 КиБ в `lite`.
- RuleBase добавляет заголовки/разметку; фактический инжект больше на 1–2 КиБ.
- Каталог навыков: ~100 описаний; DSH ограничивает длину описаний, но
  суммарно это заметный вклад. Установщик SHOULD показывать оценку.
- Сабагенты получают те же always-on правила (RuleBase инжектит всем агентам).
  Это осознанное наследование guardrails; если станет проблемой — `lite`-профиль
  или upstream-доработка RuleBase (per-agent scoping).
- Роль-пресет добавляет тело роли в persona дочернего агента; это контекст
  ребёнка, а не главной сессии. Размер роли SHOULD показываться в `--doctor`.

### 9. RU/EN и синхронизация

- По умолчанию `--dsh-lang en`: ссылки на `framework_eng`, генерация из EN.
- Если EN-файла нет — fallback RU + предупреждение; установщик не должен
  создавать «висячий» навык.
- Изменения в `framework/rules/framework-bootstrap/SKILL.md` и других
  framework-файлах MUST сопровождаться синхронизацией EN (pre-commit hook /
  `tools/sync-skill.py`), иначе DSH получит старый текст.

### 10. MCP и capabilities

- `capabilities/` в проекте уже создаётся установщиком; для DSH дополнительно
  кладём `.dsh/framework/capabilities` на EN-зеркало.
- MCP-серверы настраиваются в профиле DSH (`dsh-mcp-client`), вне этого SPEC.
  В `docs/info/dsh.md` — таблица соответствия: capability → MCP server/tool →
  пример конфигурации DSH.
- Правило `capability-resolution` продолжает ссылаться на
  `framework/capabilities/registry.yaml`; в DSH это резолвится через
  `.dsh/framework/capabilities/registry.yaml` (см. блок `AGENTS.md`).

### 11. Миграция с ручной установки

Текущее состояние машины: копии навыков в `~/.dsh/skills-1c/` и
`customSkillDirs` в `~/.dsh/profiles/web/cordis.patch.yml`.

1. Сделать резервную копию `cordis.patch.yml` и `~/.dsh/skills-1c/`.
2. Установить проектную версию: `python tools/install.py --ide dsh ...`.
3. Проверить в DSH: проектные навыки (rank 100) перекрывают глобальные копии;
   RuleBase показывает `fw-*`; `AGENTS.md` подхватился.
4. Удалить `customSkillDirs` на `skills-1c` из патча профиля и перезапустить
   DSH (правка профиля требует рестарта; правила и навыки — нет, их провайдеры
   следят за каталогами).
5. Удалить `~/.dsh/skills-1c/` после успешной проверки.
6. Запустить `--doctor`; убедиться, что дублей и битых ссылок нет.
7. Запустить DSH через `dsh-1c.ps1`/`dsh-1c.sh`, чтобы подхватить пресеты;
   проверить выбор роли и `subagent`.
8. Просмотреть `git status`: `fw-*.md`, `AGENTS.md`, `manifest.json`,
   `presets.patch.yml` и wrapper должны быть новыми/изменёнными; ссылки и
   `local.json` — отсутствовать в git.

Особенности обновления:

- RuleBase и skill-filesystem смотрят за своими каталогами: переустановка
  правил/навыков не требует перезапуска DSH.
- `AGENTS.md` читается в начале сессии; после его изменения нужна новая сессия.
- Установка/обновление плагина RuleBase в профиле требует перезапуска DSH.
- Пресеты и `--patch` применяются при запуске: после перегенерации пресетов
  нужен новый запуск через wrapper.

---

## Test plan (TDD)

### Traceability

| Требование | Слой | Тест |
|---|---|---|
| MUST 1–2: target и навыки | installer | unit: target paths; integration: `.dsh/skills/<name>/SKILL.md` существует и читается |
| MUST 3: генерация правил | generator | unit: frontmatter/backmatter вырезаны, H1 есть, файл не symlink; integration: размер < 256 КиБ |
| MUST 4: on-demand не инжектится | generator | unit: `alwaysApply:false` отсутствует в `.dsh/rules`, присутствует в `.dsh/framework/rules` |
| MUST 5: пути `.dsh/framework` | installer | integration: ссылки/копии существуют; `AGENTS.md` содержит mapping |
| MUST 6: AGENTS.md | installer | unit: идемпотентность, сохранение пользовательского текста, удаление только блока |
| MUST 7: идемпотентность | installer | integration: два запуска → одинаковый набор/хеши; dry-run не пишет |
| MUST 8: деинсталляция | installer | integration: пользовательский `team-rules.md` и навык сохранены |
| MUST 9: фантомы | graph | unit: `references/fallback-standalone.md` не попадает в компоненты |
| MUST 10: тесты | CI | matrix Windows + Linux |
| MUST 11: docs | docs | review checklist |
| MUST 12: пресеты | preset generator | unit: патч проходит tolerant-проверку (!!js), id уникальны, persona содержит роль; integration: wrapper + `--patch` |
| SHOULD 13: профили | generator | unit: parity/lite дают ожидаемые наборы и размеры |
| SHOULD 14: check | generator | unit: изменение источника → exit 1 |
| SHOULD 15: doctor | installer | integration: отчёт содержит DSH/RuleBase/root/size/presets |
| SHOULD 17: junction | installer | Windows-only: junction создаётся без Developer Mode (или skip с явным сообщением) |

### Unit tests (Python)

- `test_component_scan_ignores_reference_files`
- `test_dsh_target_paths`
- `test_dsh_rule_render_strips_frontmatter_and_backmatter`
- `test_dsh_rule_render_keeps_h1`
- `test_dsh_rule_render_excludes_on_demand`
- `test_dsh_rule_render_profile_lite`
- `test_dsh_rules_size_guard`
- `test_dsh_check_detects_drift`
- `test_dsh_agents_block_idempotent`
- `test_dsh_gitignore_managed_block`
- `test_dsh_uninstall_preserves_user_files`
- `test_dsh_skill_names_kebab_case` (аудит всех 100 навыков)
- `test_dsh_presets_patch_valid_and_ids_unique`
- `test_dsh_presets_persona_contains_role_body`
- `test_dsh_presets_lead_allows_role_ids`
- `test_dsh_presets_check_detects_dsh_version_drift`
- `test_dsh_manifest_is_portable_and_committed`
- `test_dsh_local_state_is_gitignored`

### Integration tests

Временный проект (tmpdir), `install.py --ide dsh --include ... --copy --project-dir ...`:

1. `.dsh/skills/<name>/SKILL.md` существует; frontmatter `name` валиден.
2. `.dsh/rules/fw-*.md` — обычные файлы; нет строк `^---$` в начале/конце;
   есть `# `.
3. `.dsh/framework/rules/codex-subagent-orchestration/SKILL.md` существует,
   но в `.dsh/rules` его нет.
4. `AGENTS.md` содержит маркеры; повторный запуск не дублирует блок.
5. `--dry-run` не создаёт `.dsh`.
6. `--uninstall` удаляет `fw-*`, ссылки, локальное состояние и блок; `team-rules.md`
   остаётся.
7. `--check` зелёный после установки; после правки источника — красный.
8. `.dsh/presets.patch.yml` и wrapper созданы; YAML парсится; в patch есть
   `preset-1c-lead` и роли; `manifest.json` не содержит абсолютных путей.
9. `.dsh/skills/`, `.dsh/framework`, `.dsh/local.json` отсутствуют в `git status`
   (проверка через `git check-ignore`), а `fw-*.md`, `manifest.json`,
   `presets.patch.yml` — присутствуют.

### Manual smoke (DSH)

1. `dsh plugin --profile web add github:mycodesite/dsh-rules#v0.1.10`.
2. `python tools/install.py --ide dsh --all` (или выбранный набор).
3. Запустить `./dsh-1c.sh` (Windows: `.\dsh-1c.ps1`) из корня проекта — wrapper
   добавляет `--patch .dsh/presets.patch.yml`.
4. В настройках RuleBase увидеть `fw-*` и пользовательские правила; в системном
   промпте — блок `［规则库开始］`.
5. В каталоге навыков увидеть установленные навыки; вызвать `quick-fix`.
6. Проверить, что `AGENTS.md` подхватился (упоминание фреймворка).
7. В селекторе пресетов увидеть `1c-lead`; выбрать его, вызвать `subagent` с
   `agent_preset: 1c-reviewer`; убедиться, что роль загрузилась и не спавнит детей.
8. `--doctor` — без ошибок; `--check` — зелёный; `git status` — только
   коммитируемые артефакты.

### Test Users

Не применимо: в этой задаче нет 1С-базы, ролей и пользователей. Все проверки —
файловые/CLI/DSH-сессия.

---

## Acceptance scenarios (BDD)

### Сценарий 1. Чистая установка в проект

```gherkin
Given пустой git-проект с установленным DSH и RuleBase
When я запускаю python tools/install.py --ide dsh --include skill/quick-fix rule/framework-bootstrap
Then в проекте есть .dsh/skills/quick-fix/SKILL.md
And в .dsh/rules есть fw-000-framework-bootstrap.md без YAML-блоков
And в AGENTS.md есть управляемый блок
And повторный запуск не меняет содержимое
```

### Сценарий 2. On-demand не инжектится

```gherkin
Given установлено правило codex-subagent-orchestration с alwaysApply:false
When я открываю .dsh/rules
Then в нём нет файла этого правила
And оно доступно по пути .dsh/framework/rules/codex-subagent-orchestration/SKILL.md
```

### Сценарий 3. Дрейф правил

```gherkin
Given установленный фреймворк и сгенерированные правила
When я меняю текст framework_eng/rules/framework-bootstrap/SKILL.md
And запускаю python tools/dsh_rules.py check
Then команда завершается с кодом 1 и перечисляет расхождение
```

### Сценарий 4. Деинсталляция

```gherkin
Given установленный фреймворк и пользовательское правило .dsh/rules/team-rules.md
When я запускаю python tools/install.py --ide dsh --uninstall
Then сгенерированные fw-*.md и ссылки удалены
And .dsh/rules/team-rules.md сохранён
And блок в AGENTS.md удалён, остальной текст сохранён
```

### Сценарий 5. DSH-пресеты

```gherkin
Given установлен DSH и сгенерирован .dsh/presets.patch.yml
When я запускаю dsh web --patch .dsh/presets.patch.yml
Then в селекторе пресетов есть 1c-lead и роли 1c-analyst/1c-reviewer/...
And в 1c-lead у tool-subagent есть allowedAgentPresets со всеми ролями
When я вызываю subagent с agent_preset = 1c-reviewer
Then дочерний агент получает persona ревьюера и инструменты
And у него нет delegation-группы
```

### Сценарий 6. Коммит артефактов

```gherkin
Given установленный фреймворк в git-проекте
When я выполняю git status
Then fw-*.md, AGENTS.md, manifest.json и presets.patch.yml видны как файлы
And .dsh/skills, .dsh/framework и .dsh/local.json игнорируются
```

---

## Task breakdown

Декомпозиция — в `docs/specs-and-analisys/task-breakdown-dsh.json`.
Кратко по фазам:

| Фаза | Содержание | Оценка |
|---|---|---|
| 0. Фундамент | фильтр сканирования, аудит имён, target-скелет, тесты | 0.5–1 день |
| 1. Установщик | пути, ссылки/junction, install/uninstall, detection, dry-run | 2–3 дня |
| 2. Правила и AGENTS.md | генератор, профили, манифест, check, gitignore, бюджет | 2–3 дня |
| 3. Сабагенты/пресеты | справочные пути, spike, генератор `.dsh/presets.patch.yml`, wrapper; ретиринг — опционально | 3–5 дней |
| 4. Документация и миграция | docs, doctor, CI, миграция с skills-1c | 1–2 дня |

MVP = фазы 0–4, кроме опциональных ретиринга и JS-воркфлоу: 8–12 дней.

---

## Risks and mitigations

| Риск | Влияние | Митигация |
|---|---|---|
| RuleBase пропускает симлинки | правила не работают | генерировать реальные файлы; `--check`; upstream-PR (MAY 19) |
| RuleBase инжектит в сабагентов | 59 КиБ × каждый сабагент | `lite`-профиль; замер; upstream per-agent scoping |
| 256 КиБ cap | обрезка правил | size guard 200/240 КиБ; `lite`; не дублировать пользовательские правила |
| Дрейф сгенерированных правил | агент видит старый текст | манифест + `--check` + повторная установка; read-only |
| Windows без Developer Mode | symlink не создаётся | junction-fallback; copy-fallback с предупреждением |
| DSH project root ≠ cwd | RuleBase не видит `.dsh/rules` | устанавливать в ближайший `.git`; запускать DSH из корня; `--doctor` |
| Глобальные `customSkillDirs` дублируют проектные | старые версии навыков | миграция: удалить после проверки; `--doctor` предупреждает |
| Пользователь редактирует `fw-*.md` | изменения теряются | `fw-`-префикс, документация, `--check`; read-only только без коммита |
| Коллизии rule ↔ skill | неоднозначный каталог | on-demand правила не кладём в `.dsh/skills` |
| DSH обновится и сломает контракт | установка перестанет работать | пин версии; smoke-тест; `--doctor` |
| RuleBase обновят через маркет/npm | установится одноимённый чужой пакет, DSH может не стартовать | ставить только `github:mycodesite/dsh-rules` или tarball; пиновать тег; не обновлять через маркет |
| DSH обновил `standard.patch.yml` | сгенерированные пресеты потеряли инструменты/разошлись | `--check` по версии DSH; перегенерация; spike-тест |
| Пресеты не подхватились | роли не работают, `agent_preset` не виден | wrapper с `--patch`; `--doctor`; fallback prompt в `subagent` |
| Коммит `fw-*.md` даёт merge-конфликты | конфликты при обновлении фреймворка | генерировать детерминированно; обновлять одной командой; review diff |
| `AGENTS.md` конфликтует с пользовательским | потеря текста | управляемый блок, сохранение остального, `--no-agents-md` |
| `framework/...` пути не резолвятся | агент не находит документ | mapping в `AGENTS.md`; `.dsh/framework`; `--doctor` |

---

## Open questions

Решения пользователя от 2026-11-06 зафиксированы: проектная установка, `parity`,
коммит сгенерированных артефактов, генерация DSH-пресетов в MVP.

1. **Версии.** Зафиксировано: DSH 0.2.1-rc.5, RuleBase 0.1.10; минимальная
   поддерживаемая версия RuleBase — 0.1.4+ (DSH ≥ 0.1.5-rc.1).
2. **Upstream.** Готовы ли мы отправлять PR в `dsh-rules` на симлинки/скоупинг,
   или ограничиваемся генерацией? Пока не отправляли.
3. **AGENTS.md.** Реализовано автосоздание управляемого блока; отключается
   `--dsh-no-agents-md`.
4. **Глобальные пресеты.** Реализован только проектный `--patch` + wrapper;
   opt-in слияние в профиль (`--dsh-install-presets-profile`) пока печатает
   предупреждение и не выполняет merge.

---

## Decision log (ADR)

| # | Решение | Обоснование |
|---|---|---|
| D1 | Проектная установка в `.dsh/` | решение пользователя; изоляция 1С-правил; RuleBase project-уровень |
| D2 | Always-on правила — реальные файлы, не симлинки | RuleBase 0.1.10 отбрасывает симлинки |
| D3 | On-demand — в `.dsh/framework`, не в `.dsh/rules` | семантика ленивой загрузки; экономия контекста |
| D4 | `parity` по умолчанию | решение пользователя; сохраняет текущее поведение фреймворка; `lite` — после ретиринга |
| D5 | DSH-пресеты генерируются в MVP | решение пользователя; роли должны быть доступны через `agent_preset`, а не только prompt |
| D6 | Коммитятся `fw-*.md`, `AGENTS.md`, `manifest.json`, `presets.patch.yml`, wrapper | решение пользователя; воспроизводимость и review изменений |
| D7 | Ссылки `.dsh/skills`, `.dsh/framework` и `.dsh/local.json` не коммитятся | машинно-зависимы; ломаются на другой машине |
| D8 | Пресеты — проектный `.dsh/presets.patch.yml` + wrapper; глобальное слияние только opt-in | DSH не обнаруживает проектные пресеты; проектная изоляция |
| D9 | `AGENTS.md` — короткий блок-карта | DSH не поддерживает @-импорты; правила уже инжектятся RuleBase |
