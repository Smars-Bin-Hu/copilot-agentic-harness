// Colours for code, by the type of the file or the language of a fenced block: SQL, Bash, PowerShell, Python, C#, JSON, YAML, XML, CSV and a few more.
// A small scanner, no library and no network (a saved copy of the page may call out for nothing). It is not a parser: it only tells a comment,
// a string, a keyword, a number, a variable and a name before `(` from the rest, so a wrong guess costs a wrong colour and never the text.
// What it returns is text and `span` nodes made with textContent: nothing in a file can become markup.
"use strict";

const Highlight = (function () {
  const MAX_CHARS = 300000;  // a longer file is shown plain
  const CSV_MAX_CHARS = 120000;  // a cell is two nodes: a long table is shown plain
  const words = (text) => new Set(text.split(/\s+/).filter(Boolean));

  const SQL_KW = words(`select from where and or not in is null like between exists join inner left right full outer cross on group by order having union all distinct as top
    case when then else end insert into values update set delete merge using matched create alter drop table view index procedure proc function trigger database schema
    if begin declare exec execute return while print go with nolock over partition rows range unbounded preceding following current row limit offset truncate constraint
    primary key foreign references default identity output cast convert try catch throw raiserror transaction commit rollback tran grant revoke deny asc desc intersect except
    apply unique check clustered nonclustered add column rename to for each of into after before instead use waitfor break continue goto fetch next cursor open close deallocate`);
  const SQL_TYPES = words(`int bigint smallint tinyint bit decimal numeric float real money smallmoney varchar nvarchar char nchar text ntext date datetime datetime2 smalldatetime
    time datetimeoffset uniqueidentifier varbinary binary image xml sql_variant timestamp rowversion string number boolean integer double`);
  const BASH_KW = words(`if then else elif fi for while until do done case esac in function select return exit export local readonly set unset source eval exec trap shift break
    continue declare typeset`);
  const BASH_BUILTIN = words(`echo printf cd ls cat grep sed awk read test true false pwd mkdir rm cp mv chmod chown curl wget python python3 pip git sudo find xargs sort uniq head tail
    cut tr wc tee date sleep kill ps env which dirname basename tar zip unzip ssh scp make docker`);
  const PS_KW = words(`function filter if else elseif foreach for while do until switch return param begin process end try catch finally throw trap break continue exit in class enum
    using data dynamicparam workflow parallel sequence`);
  const BAT_KW = words(`if else goto echo set call for in do exit not exist defined errorlevel setlocal endlocal shift pause cd md rd del copy move type start`);
  const PY_KW = words(`and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try
    while with yield match case`);
  const PY_CONST = words(`True False None`);
  const PY_BUILTIN = words(`print len range int str float bool list dict set tuple open isinstance enumerate zip map filter sorted sum min max abs super type self cls Exception
    ValueError KeyError TypeError object bytes any all repr id iter next format round getattr setattr hasattr`);
  const CS_KW = words(`abstract as base bool break byte case catch char checked class const continue decimal default delegate do double else enum event explicit extern false finally
    fixed float for foreach goto if implicit in int interface internal is lock long namespace new null object operator out override params private protected public readonly ref
    return sbyte sealed short sizeof stackalloc static string struct switch this throw true try typeof uint ulong unchecked unsafe ushort using virtual void volatile while var
    async await get set value yield record init required partial where select from orderby let join group into when with dynamic nameof`);
  const C_KW = words(`abstract as async await boolean break byte case catch char class const continue debugger default delete do double else enum export extends extern false final finally
    float for foreach fn fun func function go goto if implements import in instanceof int interface let long namespace new null of package private protected public return short
    static string struct super switch synchronized this throw throws true try type typeof undefined val var void volatile while with yield def object trait match lazy override
    sealed unsigned signed auto inline template typename using virtual nullptr self`);
  const JSON_KW = words(`true false null`);
  const YAML_KW = words(`true false null yes no on off`);
  const CSS_KW = words(`important inherit initial none auto`);

  // spec: line / block: how a comment starts; wordStart: a line comment only after a space or `;` (Bash `$#`); strings: [open, close, escape, multi-line];
  // the escape is a character (`\`), "dbl" (the quote doubled) or "" ; stringStart: what may stand before a string (YAML: `don't` is not one); ci: keywords in any case;
  // extra: [sticky regex, class] tried before names and numbers; keys: a JSON string followed by `:` is a key; caps: a Capitalised name is a type.
  const SPECS = {
    sql: {label: "SQL", ci: true, line: ["--"], block: [["/*", "*/"]], strings: [["'", "'", "dbl", true], ['"', '"', "dbl", false]], kw: SQL_KW, types: SQL_TYPES,
      extra: [[/@@?\w+|#{1,2}\w+/y, "var"], [/\[[^\]\r\n]*\]/y, "id"]]},
    bash: {label: "Bash", line: ["#"], wordStart: true, strings: [["'", "'", "", true], ['"', '"', "\\", true]], kw: BASH_KW, builtin: BASH_BUILTIN,
      extra: [[/\$\{[^}\r\n]*\}|\$[A-Za-z_]\w*|\$[0-9@#?!*$-]|\$\(\(?/y, "var"], [/(?<=\s)--?[A-Za-z][\w-]*/y, "id"]]},
    powershell: {label: "PowerShell", ci: true, line: ["#"], wordStart: true, block: [["<#", "#>"]], strings: [["'", "'", "dbl", true], ['"', '"', "`", true]], kw: PS_KW,
      extra: [[/\$\{[^}\r\n]*\}|\$(?:\w+:)?\w+|\$_/y, "var"], [/[A-Za-z]+-[A-Za-z]+/y, "fn"], [/(?<=\s)-[A-Za-z]\w*/y, "id"]]},
    batch: {label: "Batch", ci: true, line: ["::"], strings: [['"', '"', "", false]], kw: BAT_KW,
      extra: [[/\brem\b[^\r\n]*/iy, "com"], [/%~?[\w:.~=*,-]+%?|%%~?\w/y, "var"]]},
    python: {label: "Python", strings: [['"""', '"""', "\\", true], ["'''", "'''", "\\", true], ['"', '"', "\\", false], ["'", "'", "\\", false]], line: ["#"], kw: PY_KW, consts: PY_CONST, builtin: PY_BUILTIN,
      extra: [[/@[A-Za-z_][\w.]*/y, "type"]]},
    csharp: {label: "C#", line: ["//"], block: [["/*", "*/"]], caps: true, strings: [['$@"', '"', "dbl", true], ['@$"', '"', "dbl", true], ['@"', '"', "dbl", true], ['"', '"', "\\", false], ["'", "'", "\\", false]],
      kw: CS_KW, extra: [[/#\s*(?:region|endregion|if|else|elif|endif|define|undef|pragma|nullable|line)\b[^\r\n]*/y, "meta"]]},
    json: {label: "JSON", strings: [['"', '"', "\\", false]], keys: true, kw: JSON_KW},
    yaml: {label: "YAML", ci: true, line: ["#"], wordStart: true, strings: [['"', '"', "\\", false], ["'", "'", "dbl", false]], stringStart: /[\s[{,:-]/, kw: YAML_KW,
      extra: [[/[A-Za-z_][\w.\-/]*(?=[ \t]*:(?:[ \t]|\r?\n|$))/y, "key"]]},
    xml: {label: "XML", block: [["<!--", "-->"]], strings: [],
      extra: [[/<\?[\s\S]*?\?>/y, "meta"], [/<!\[CDATA\[[\s\S]*?\]\]>/y, "str"], [/<\/?[A-Za-z_][\w:.-]*/y, "kw"], [/(?<==\s*)(?:"[^"]*"|'[^']*')/y, "str"],
        [/[A-Za-z_:][\w:.-]*(?=\s*=)/y, "key"], [/&#?\w+;/y, "num"]]},
    ini: {label: "INI", ci: true, line: ["#", ";"], wordStart: true, strings: [['"', '"', "\\", false], ["'", "'", "", false]], stringStart: /[\s=:[{,]/, kw: words("true false"),
      extra: [[/\[[^\]\r\n]+\](?=[ \t]*(?:\r?\n|$))/y, "type"], [/[A-Za-z_][\w.\-]*(?=[ \t]*[=:])/y, "key"]]},
    css: {label: "CSS", block: [["/*", "*/"]], strings: [['"', '"', "\\", false], ["'", "'", "\\", false]], kw: CSS_KW,
      extra: [[/@[\w-]+/y, "kw"], [/--[\w-]+/y, "var"], [/#[0-9a-fA-F]{3,8}\b/y, "num"], [/[A-Za-z-]+(?=\s*:\s)/y, "key"]]},
  };
  const CLIKE = {line: ["//"], block: [["/*", "*/"]], caps: true, strings: [['"', '"', "\\", false], ["'", "'", "\\", false], ["`", "`", "\\", true]], kw: C_KW};
  for (const [name, label] of [["js", "JavaScript"], ["ts", "TypeScript"], ["java", "Java"], ["scala", "Scala"], ["go", "Go"], ["c", "C"], ["cpp", "C++"], ["kotlin", "Kotlin"]]) SPECS[name] = Object.assign({label}, CLIKE);

  // the type of a file, or the name of a language after the three backticks of a block, -> the language here ("" : none)
  const ALIASES = {
    sql: "sql", tsql: "sql", psql: "sql", sh: "bash", bash: "bash", zsh: "bash", shell: "bash", console: "bash", ps1: "powershell", psm1: "powershell", psd1: "powershell",
    powershell: "powershell", pwsh: "powershell", bat: "batch", cmd: "batch", batch: "batch", py: "python", python: "python", python3: "python", cs: "csharp", csx: "csharp",
    csharp: "csharp", "c#": "csharp", json: "json", jsonl: "json", jsonc: "json", yml: "yaml", yaml: "yaml", xml: "xml", html: "xml", htm: "xml", xhtml: "xml", svg: "xml", csproj: "xml",
    ini: "ini", cfg: "ini", conf: "ini", toml: "ini", properties: "ini", env: "ini", css: "css", js: "js", javascript: "js", jsx: "js", mjs: "js", ts: "ts", tsx: "ts", typescript: "ts",
    java: "java", scala: "scala", go: "go", golang: "go", c: "c", h: "c", cpp: "cpp", "c++": "cpp", hpp: "cpp", kt: "kotlin", kotlin: "kotlin", csv: "csv", tsv: "tsv",
    diff: "diff", patch: "diff",
  };
  const LABELS = {csv: "CSV", tsv: "TSV", diff: "Diff"};

  // "DEV/x/load.SQL" -> "sql"; "```bash" -> "bash"; "```sql title=x" -> "sql"; a name that is nothing known -> "".
  function language(name) {
    const word = String(name || "").trim().split(/[\s{]/)[0].toLowerCase();
    const base = word.split("/").pop();
    const dot = base.lastIndexOf(".");
    const key = dot >= 0 ? base.slice(dot + 1) : base;
    return Object.prototype.hasOwnProperty.call(ALIASES, key) ? ALIASES[key] : "";
  }

  function label(lang) { return lang && SPECS[lang] ? SPECS[lang].label : LABELS[lang] || ""; }

  // --- the scanner -------------------------------------------------------------------------------------------

  function scan(text, spec) {
    const out = [];
    let plain = "";
    const push = (cls, value) => {
      if (!cls) { plain += value; return; }
      if (plain) { out.push(["", plain]); plain = ""; }
      out.push([cls, value]);
    };
    const kinds = spec.kw ? spec.kw : new Set();
    const n = text.length;
    let i = 0;
    outer:
    while (i < n) {
      const ch = text[i];
      if (ch === " " || ch === "\t" || ch === "\n" || ch === "\r") { plain += ch; i += 1; continue; }
      const before = i === 0 ? "\n" : text[i - 1];
      for (const mark of spec.line || []) {
        if (text.startsWith(mark, i) && (!spec.wordStart || /[\s;&|(]/.test(before))) {
          let end = text.indexOf("\n", i);
          if (end < 0) end = n;
          push("com", text.slice(i, end)); i = end;
          continue outer;
        }
      }
      for (const [open, close] of spec.block || []) {
        if (text.startsWith(open, i)) {
          const end = text.indexOf(close, i + open.length);
          const stop = end < 0 ? n : end + close.length;
          push("com", text.slice(i, stop)); i = stop;
          continue outer;
        }
      }
      for (const [open, close, escape, multi] of spec.strings || []) {
        if (!text.startsWith(open, i) || (spec.stringStart && !spec.stringStart.test(before))) continue;
        let j = i + open.length;
        while (j < n) {
          const c = text[j];
          if (escape && escape !== "dbl" && c === escape) { j += 2; continue; }
          if (text.startsWith(close, j)) {
            if (escape === "dbl" && text.startsWith(close + close, j)) { j += close.length * 2; continue; }
            j += close.length;
            break;
          }
          if (!multi && c === "\n") break;
          j += 1;
        }
        j = Math.min(j, n);
        let cls = "str";
        if (spec.keys) { const after = /\s*:/y; after.lastIndex = j; if (after.test(text)) cls = "key"; }
        push(cls, text.slice(i, j)); i = j;
        continue outer;
      }
      for (const [pattern, cls] of spec.extra || []) {
        pattern.lastIndex = i;
        const found = pattern.exec(text);
        if (found && found[0].length) { push(cls, found[0]); i += found[0].length; continue outer; }
      }
      if (ch >= "0" && ch <= "9" && !/[\w$]/.test(before)) {
        const number = /0[xX][0-9a-fA-F_]+|\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?/y;
        number.lastIndex = i;
        const found = number.exec(text);
        if (found) { push("num", found[0]); i += found[0].length; continue; }
      }
      if (/[A-Za-z_]/.test(ch)) {
        const name = /[A-Za-z_][\w]*/y;
        name.lastIndex = i;
        const word = name.exec(text)[0];
        const key = spec.ci ? word.toLowerCase() : word;
        let cls = "";
        if (before !== "." && kinds.has(key)) cls = "kw";
        else if (before !== "." && spec.types && spec.types.has(key)) cls = "type";
        else if (spec.consts && spec.consts.has(key)) cls = "num";
        else if (spec.builtin && spec.builtin.has(key)) cls = "builtin";
        else if (text[i + word.length] === "(") cls = "fn";
        else if (spec.caps && ch >= "A" && ch <= "Z" && word.length > 1 && word !== word.toUpperCase()) cls = "type";
        push(cls, word); i += word.length;
        continue;
      }
      plain += ch; i += 1;
    }
    if (plain) out.push(["", plain]);
    return out;
  }

  // A CSV column has its own colour (six in turn), the first row is the header. A quote opens a cell that may hold line breaks and the delimiter.
  function table(text, delimiter) {
    const out = [];
    let i = 0, column = 0, row = 0;
    const n = text.length;
    while (i < n) {
      const ch = text[i];
      if (ch === "\n") { out.push(["", ch]); i += 1; column = 0; row += 1; continue; }
      if (ch === "\r") { out.push(["", ch]); i += 1; if (text[i] !== "\n") { column = 0; row += 1; } continue; }  // a lone CR ends a row too
      if (ch === delimiter) { out.push(["sep", ch]); i += 1; column += 1; continue; }
      let j = i;
      if (ch === '"') {
        j += 1;
        while (j < n) {
          if (text[j] === '"') { if (text[j + 1] === '"') { j += 2; continue; } j += 1; break; }
          j += 1;
        }
      }
      while (j < n && text[j] !== delimiter && text[j] !== "\n" && text[j] !== "\r") j += 1;
      out.push(["c" + (column % 6) + (row === 0 ? " hd" : ""), text.slice(i, j)]);
      i = j;
    }
    return out;
  }

  function patch(text) {
    return text.split("\n").map((line, index, all) => {
      const value = index < all.length - 1 ? line + "\n" : line;
      const cls = /^(\+\+\+|---|diff |index )/.test(line) ? "kw" : line.startsWith("@@") ? "type" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "";
      return [cls, value];
    }).filter((token) => token[1] !== "");
  }

  // [[class, text], ...] for the text: put together again, the texts are the text. A language not known, or a text too long, is one piece with no class.
  function tokens(text, lang) {
    const csv = lang === "csv" || lang === "tsv";
    if (!lang || text.length > (csv ? CSV_MAX_CHARS : MAX_CHARS) || (!csv && lang !== "diff" && !SPECS[lang])) return [["", text]];
    if (csv) return table(text, lang === "csv" ? "," : "\t");
    if (lang === "diff") return patch(text);
    return scan(text, SPECS[lang]);
  }

  // The nodes for a code block: text and coloured spans.
  function nodes(text, lang) {
    return tokens(text, lang).map(([cls, value]) => (cls ? h("span", {class: cls.split(" ").map((name) => "tok-" + name).join(" ")}, value) : document.createTextNode(value)));
  }

  return {language, label, tokens, nodes};
})();

if (typeof module !== "undefined" && module.exports) module.exports = Highlight;
