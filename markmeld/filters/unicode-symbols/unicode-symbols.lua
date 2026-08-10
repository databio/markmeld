--[[
unicode-symbols.lua -- make pasted Unicode operators survive a LaTeX build.

Authors type "≤ 10 minutes" straight into markdown, or paste a sentence out of
Word, a spreadsheet or a collaborator's email. pandoc's default PDF engine is
pdflatex, and the LaTeX templates in use here fall through to
`\usepackage[utf8]{inputenc}`, which has no mapping for the Mathematical
Operators block. The whole document then fails to build:

    ! LaTeX Error: Unicode character ≤ (U+2264) not set up for use with LaTeX.

This filter rewrites those characters into LaTeX math on the way out, so the
symbol the author typed is the symbol that appears in the PDF.

Scope, deliberately narrow: the arithmetic and comparison operators, and
nothing else. It is not a Unicode-to-LaTeX table.

  * Greek letters are out. A "α" in prose is an authoring decision -- the
    author means a variable and should write `$\alpha$` -- and silently
    mathifying a whole alphabet changes far more documents than it fixes.
  * Punctuation, dashes and accented letters are out. inputenc already handles
    them, and they are text, not math.

× ÷ ± are included even though current LaTeX renders them from inputenc
unaided, so that "the operators you paste become math" is a rule with no
exceptions to remember. Their appearance is unchanged.

The filter only installs itself for LaTeX output; every other writer sees the
document untouched. It rewrites `Str` elements only, so inline code, code
blocks, raw blocks and existing `$...$` math (a `Math` element, not a `Str`)
are never rewritten.
--]]

--- Codepoint -> the LaTeX math that draws it.
local MATH = {
  [0x2264] = "\\le",      -- ≤ LESS-THAN OR EQUAL TO
  [0x2265] = "\\ge",      -- ≥ GREATER-THAN OR EQUAL TO
  [0x2260] = "\\neq",     -- ≠ NOT EQUAL TO
  [0x2248] = "\\approx",  -- ≈ ALMOST EQUAL TO
  [0x223C] = "\\sim",     -- ∼ TILDE OPERATOR
  [0x2212] = "-",         -- − MINUS SIGN (not the hyphen U+002D)
  [0x00D7] = "\\times",   -- × MULTIPLICATION SIGN
  [0x00F7] = "\\div",     -- ÷ DIVISION SIGN
  [0x00B1] = "\\pm",      -- ± PLUS-MINUS SIGN
}

--- Split one string into Str / RawInline pieces, or nil if it holds no operators.
local function split(text)
  local pieces = {}
  local plain = {}
  local found = false

  local function flush()
    if #plain > 0 then
      pieces[#pieces + 1] = pandoc.Str(table.concat(plain))
      plain = {}
    end
  end

  for _, code in utf8.codes(text) do
    local math = MATH[code]
    if math then
      found = true
      flush()
      pieces[#pieces + 1] = pandoc.RawInline("latex", "\\ensuremath{" .. math .. "}")
    else
      plain[#plain + 1] = utf8.char(code)
    end
  end

  if not found then
    return nil  -- unchanged; let pandoc keep the original element
  end
  flush()
  return pieces
end

if FORMAT:match("latex") or FORMAT:match("beamer") then
  return {{
    Str = function(el)
      return split(el.text)
    end,
  }}
end

return {}
