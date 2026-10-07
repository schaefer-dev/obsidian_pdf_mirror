-- pandoc Lua filter: turns Obsidian-specific constructs into Typst.
-- Expects metadata `vaultroot` (absolute path) and `notedir` (vault-relative
-- directory of the note). Inline wikilinks/embeds are already rewritten by
-- mirror.py before pandoc sees the text.

local stringify = pandoc.utils.stringify
local path = pandoc.path

local vaultroot = ""
local notedir = ""

local IMAGE_EXTS = { png = true, jpg = true, jpeg = true, gif = true, svg = true, webp = true }
local QUERY_BLOCKS = { dataview = true, dataviewjs = true, tasks = true, query = true }

local function typst(blocks_or_inlines, is_inline)
  local doc
  if is_inline then
    doc = pandoc.Pandoc({ pandoc.Plain(blocks_or_inlines) })
  else
    doc = pandoc.Pandoc(blocks_or_inlines)
  end
  return (pandoc.write(doc, "typst"):gsub("%s+$", ""))
end

local function typst_string(s)
  return '"' .. s:gsub("\\", "\\\\"):gsub('"', '\\"') .. '"'
end

local function callout_block(kind, title_inlines, body_blocks)
  local title = "none"
  if title_inlines and #title_inlines > 0 then
    title = "[" .. typst(title_inlines, true) .. "]"
  end
  return pandoc.RawBlock("typst",
    "#callout(kind: " .. typst_string(kind) .. ", title: " .. title .. ")[\n"
    .. typst(body_blocks or {}) .. "\n]")
end

local function file_exists(p)
  local f = io.open(p, "rb")
  if f then f:close() return true end
  return false
end

local function url_decode(s)
  return (s:gsub("%%(%x%x)", function(h) return string.char(tonumber(h, 16)) end))
end

local function placeholder(label, name)
  return pandoc.Emph({ pandoc.Str("[" .. label .. ": " .. name .. "]") })
end

-- Resolve an image source to a vault-root-relative path ("/dir/img.png"),
-- which is what `typst compile --root <vault>` expects.
local function resolve_image(src)
  src = url_decode(src)
  local candidates = {}
  if src:sub(1, 1) == "/" then
    table.insert(candidates, src:sub(2))
  else
    if notedir ~= "" then table.insert(candidates, path.join({ notedir, src })) end
    table.insert(candidates, src)
  end
  for _, rel in ipairs(candidates) do
    rel = path.normalize(rel)
    if rel:sub(1, 2) ~= ".." and file_exists(path.join({ vaultroot, rel })) then
      return "/" .. rel
    end
  end
  return nil
end

local function Meta(meta)
  vaultroot = stringify(meta.vaultroot or "")
  notedir = stringify(meta.notedir or "")
  if notedir == "." then notedir = "" end
end

local function Image(el)
  local src = el.src
  local name = path.filename(url_decode(src))
  if src:match("^%a[%w+.-]*:") then
    return pandoc.Link({ placeholder("external image", name) }, src)
  end
  local ext = (name:match("%.([^.]+)$") or ""):lower()
  if not IMAGE_EXTS[ext] then
    return placeholder("attachment", name)
  end
  local resolved = resolve_image(src)
  if not resolved then
    return placeholder("missing image", name)
  end
  el.src = resolved
  return el
end

-- Links to other notes (relative targets) become plain text; web links stay.
local function Link(el)
  if el.target:match("^%a[%w+.-]*:") then
    return el
  end
  return pandoc.Emph(el.content)
end

-- "[ ] foo" / "[x] foo" at the start of a list item -> checkbox.
local function task_marker(inlines)
  local first = inlines[1]
  if not first or first.t ~= "Str" then return nil end
  local state = first.text:match("^%[(.)%]$")
  if state then
    inlines:remove(1)
  elseif first.text == "[" and inlines[2] and inlines[2].t == "Space"
      and inlines[3] and inlines[3].t == "Str" and inlines[3].text == "]" then
    state = " "
    inlines:remove(1); inlines:remove(1); inlines:remove(1)
  else
    return nil
  end
  if inlines[1] and inlines[1].t == "Space" then inlines:remove(1) end
  inlines:insert(1, pandoc.RawInline("typst", "#task(" .. typst_string(state) .. ")"))
  return true
end

local function BulletList(el)
  for _, item in ipairs(el.content) do
    local first = item[1]
    if first and (first.t == "Plain" or first.t == "Para") then
      task_marker(first.content)
    end
  end
  return el
end

local function OrderedList(el)
  return BulletList(el)
end

-- > [!type]+/- Optional title
-- > body
local function BlockQuote(el)
  local first = el.content[1]
  if not first or (first.t ~= "Para" and first.t ~= "Plain") then return nil end
  local head = first.content[1]
  if not head or head.t ~= "Str" then return nil end
  local kind, rest = head.text:match("^%[!([%w_-]+)%][+-]?(.*)$")
  if not kind then return nil end

  local inlines = first.content
  local title = pandoc.Inlines({})
  if rest ~= "" then title:insert(pandoc.Str(rest)) end
  local i = 2
  while i <= #inlines and inlines[i].t ~= "LineBreak" and inlines[i].t ~= "SoftBreak" do
    title:insert(inlines[i])
    i = i + 1
  end
  while #title > 0 and title[1].t == "Space" do title:remove(1) end

  local body = pandoc.Blocks({})
  if i < #inlines then
    local restinl = pandoc.Inlines({})
    for j = i + 1, #inlines do restinl:insert(inlines[j]) end
    body:insert(pandoc.Para(restinl))
  end
  for j = 2, #el.content do body:insert(el.content[j]) end
  return callout_block(kind:lower(), title, body)
end

-- ::: {.obsidian-embed title="..."} produced by mirror.py for ![[Note]]
local function Div(el)
  if el.classes:includes("obsidian-embed") then
    local title = el.attributes["title"] or ""
    return callout_block("embed", { pandoc.Str(title) }, el.content)
  end
  return nil
end

-- [label]{.wikilink} produced by mirror.py for [[Note|label]]
local function Span(el)
  if el.classes:includes("wikilink") then
    local out = pandoc.Inlines({ pandoc.RawInline("typst", "#text(fill: accent)[") })
    out:extend(el.content)
    out:insert(pandoc.RawInline("typst", "]"))
    return out
  end
  return nil
end

local function CodeBlock(el)
  local lang = el.classes[1]
  if lang and QUERY_BLOCKS[lang] then
    return callout_block("dataview", nil, { pandoc.CodeBlock(el.text) })
  end
  return nil
end

return {
  { Meta = Meta },
  {
    Image = Image,
    Link = Link,
    Span = Span,
    BulletList = BulletList,
    OrderedList = OrderedList,
    CodeBlock = CodeBlock,
    Div = Div,
    BlockQuote = BlockQuote,
  },
}
