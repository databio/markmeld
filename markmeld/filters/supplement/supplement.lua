--[[
supplement.lua — inject the canonical supplementary-section preamble (LaTeX).

Two ways to trigger it:

1. Explicit marker — a fenced div anywhere the supplement begins:

       ::: supplement
       :::

2. Automatic — set a frontmatter flag and the preamble is injected before the
   FIRST section (any level) whose heading starts with "Supplement":

       ---
       auto_supplement: true
       ---

   ...so the author writes nothing extra; their normal "Supplementary ..."
   heading is the trigger.

The injected preamble:
  * \clearpage  — start the supplement on a fresh page AND flush pending floats
  * \onecolumn
  * figure/table counters reset to S1, S2, ...
  * \def\fps@figure{H} — every supplementary figure is placed exactly where it
    appears (strict, non-floating, in source order). Supplementary figures must
    never reorder to fit a page.

Use ONE trigger, not both. If a `::: supplement` div is present it wins, and the
auto flag is skipped, so the preamble is injected exactly once.

Note: with the `section_divs` reader extension (which markmeld/pandoc enable),
each section is a `Div` of class "section" wrapping its `Header`, so the
auto-detection matches both a bare top-level `Header` and a section `Div`.
]]

local PREAMBLE = table.concat({
  "\\clearpage",
  "\\onecolumn",
  "\\setcounter{figure}{0}\\renewcommand{\\thefigure}{S\\arabic{figure}}\\renewcommand{\\thetable}{S\\arabic{table}}",
  "\\makeatletter\\def\\fps@figure{H}\\makeatother",
}, "\n")

-- set when the explicit ::: supplement div handles injection, so the auto-flag
-- path (which runs last, in Pandoc) knows not to inject a second time.
local injected_via_div = false

function Div(el)
  if not FORMAT:match("latex") then
    return nil
  end
  if not el.classes:includes("supplement") then
    return nil
  end
  injected_via_div = true
  local blocks = { pandoc.RawBlock("latex", PREAMBLE) }
  for _, b in ipairs(el.content) do
    table.insert(blocks, b)
  end
  return blocks
end

local function flag_on(meta)
  local v = meta and meta["auto_supplement"]
  if v == nil or v == false then
    return false
  end
  if v == true then
    return true
  end
  local ok, s = pcall(pandoc.utils.stringify, v)
  return ok and s:lower() == "true"
end

-- A top-level block that represents a heading: either a bare Header, or a
-- section Div (section_divs) whose first child is a Header.
local function heading_text(b)
  if b.t == "Header" then
    return pandoc.utils.stringify(b)
  end
  if b.t == "Div" and b.content and b.content[1] and b.content[1].t == "Header" then
    return pandoc.utils.stringify(b.content[1])
  end
  return nil
end

function Pandoc(doc)
  if not FORMAT:match("latex") then
    return nil
  end
  if injected_via_div then
    return nil  -- explicit div already injected the preamble
  end
  if not flag_on(doc.meta) then
    return nil
  end
  for i, b in ipairs(doc.blocks) do
    local h = heading_text(b)
    if h and h:match("^%s*[Ss]upplement") then
      table.insert(doc.blocks, i, pandoc.RawBlock("latex", PREAMBLE))
      return doc
    end
  end
  return nil
end
