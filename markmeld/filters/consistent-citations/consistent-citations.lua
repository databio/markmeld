-- consistent-citations.lua
-- Pandoc Lua filter for consistent cross-document citation numbering.
--
-- When multiple documents share a citation namespace (e.g., grant proposals),
-- this filter ensures that citation numbers are consistent across all documents.
--
-- Metadata fields:
--   citation_group_sources: list of absolute paths to all markdown source files
--                           in the citation group (including the current document)
--   suppress-bibliography:  if true, remove the bibliography from output
--   bibliography-only:      if true, output ONLY the bibliography

-- Require pandoc >= 2.1 (uses pandoc.utils.citeproc if >= 2.19.1, else shells out)
if PANDOC_VERSION == nil then
  error("ERROR: pandoc >= 2.1 required for consistent-citations filter")
end

local has_citeproc_api = PANDOC_VERSION >= {2,19,1}

--- Run citeproc on a document, using the Lua API if available or shelling out.
-- @param doc A pandoc document AST
-- @return The document with citations resolved
local function run_citeproc(doc)
  if has_citeproc_api then
    return pandoc.utils.citeproc(doc)
  end
  -- Fallback for pandoc < 2.19: use pandoc.utils.run_json_filter
  -- to run pandoc --citeproc as a JSON-to-JSON filter
  local bib = pandoc.utils.stringify(doc.meta.bibliography or "")
  local csl = pandoc.utils.stringify(doc.meta.csl or "")
  local args = {"--citeproc"}
  if bib ~= "" then
    table.insert(args, "--bibliography")
    table.insert(args, bib)
  end
  if csl ~= "" then
    table.insert(args, "--csl")
    table.insert(args, csl)
  end
  -- run_json_filter sends the doc as JSON to the program and reads JSON back
  local result = pandoc.utils.run_json_filter(doc, "pandoc", args)
  return result
end

--- Collect citation keys from a document's Cite nodes in first-appearance order.
-- @param doc A pandoc document AST
-- @return A list of citation key strings (deduplicated, in order of appearance)
local function collect_citation_keys(doc)
  local keys = {}
  local seen = {}
  pandoc.walk_block(pandoc.Div(doc.blocks), {
    Cite = function(cite)
      for _, citation in ipairs(cite.citations) do
        if not seen[citation.id] then
          seen[citation.id] = true
          table.insert(keys, citation.id)
        end
      end
    end
  })
  return keys
end

--- Read metadata list field as a Lua table of strings.
-- Handles MetaList, MetaInlines, and MetaString types.
-- @param meta_field The metadata field value
-- @return A table of strings, or nil if field is not a list
local function meta_list_to_strings(meta_field)
  if meta_field == nil then
    return nil
  end
  local result = {}
  -- MetaList: iterate over items
  local items = meta_field
  -- If it's a MetaList, iterate; if single value, wrap in table
  if type(meta_field) == "table" then
    -- Check if it's a list (has numeric keys) or a single meta value
    if meta_field.tag == "MetaInlines" or meta_field.tag == "MetaString" then
      -- Single value, wrap as a list
      items = {meta_field}
    end
    -- Iterate over items (works for MetaList and plain tables)
    for _, item in ipairs(items) do
      local s = pandoc.utils.stringify(item)
      if s and s ~= "" then
        table.insert(result, s)
      end
    end
  end
  return result
end

--- Phase 1-2: Collect citation keys from all sibling sources and inject phantom citations.
local function collect_and_inject_phantoms(doc)
  local sources = meta_list_to_strings(doc.meta.citation_group_sources)
  if not sources or #sources == 0 then
    -- No citation group sources; pass through unchanged
    return nil
  end

  -- Collect canonical citation key ordering from all source files
  local canonical_keys = {}
  local seen = {}

  for _, source_path in ipairs(sources) do
    local fh = io.open(source_path, "r")
    if fh then
      local content = fh:read("*a")
      fh:close()
      local parsed = pandoc.read(content, "markdown")
      local keys = collect_citation_keys(parsed)
      for _, key in ipairs(keys) do
        if not seen[key] then
          seen[key] = true
          table.insert(canonical_keys, key)
        end
      end
    else
      io.stderr:write("consistent-citations: WARNING: Could not open source file: " .. source_path .. "\n")
    end
  end

  if #canonical_keys == 0 then
    return nil
  end

  -- Create a phantom Cite node with ALL canonical keys in order
  local citations = {}
  for _, key in ipairs(canonical_keys) do
    table.insert(citations, pandoc.Citation(key, "NormalCitation"))
  end

  local cite_inlines = pandoc.Cite(
    {pandoc.Str("PHANTOM")},
    citations
  )

  local phantom_para = pandoc.Para({cite_inlines})
  local phantom_div = pandoc.Div({phantom_para}, pandoc.Attr("", {"citation-group-phantom"}))

  -- Insert phantom div at the beginning of the document
  table.insert(doc.blocks, 1, phantom_div)

  return doc
end

--- Phase 3-4: Run citeproc internally and strip phantom output.
local function run_citeproc_and_cleanup(doc)
  local sources = meta_list_to_strings(doc.meta.citation_group_sources)
  if not sources or #sources == 0 then
    return nil
  end

  -- Run citeproc on the document (which now includes phantom citations)
  doc = run_citeproc(doc)

  -- Remove the phantom div from the output
  local cleaned_blocks = pandoc.List()
  for _, block in ipairs(doc.blocks) do
    local dominated_by_phantom = false
    if block.tag == "Div" and block.classes then
      for _, cls in ipairs(block.classes) do
        if cls == "citation-group-phantom" then
          dominated_by_phantom = true
          break
        end
      end
    end
    if not dominated_by_phantom then
      cleaned_blocks:insert(block)
    end
  end
  doc.blocks = cleaned_blocks

  return doc
end

--- Phase 5: Handle bibliography-only and suppress-bibliography modes.
local function handle_output_mode(doc)
  local sources = meta_list_to_strings(doc.meta.citation_group_sources)
  if not sources or #sources == 0 then
    return nil
  end

  local bib_only = doc.meta["bibliography-only"]
  local suppress_bib = doc.meta["suppress-bibliography"]

  -- Convert MetaBool or MetaInlines to boolean
  local function meta_to_bool(val)
    if val == nil then return false end
    if type(val) == "boolean" then return val end
    local s = pandoc.utils.stringify(val)
    return s == "true" or s == "yes"
  end

  if meta_to_bool(bib_only) then
    -- Find the refs div and output ONLY that
    local refs_div = nil
    for _, block in ipairs(doc.blocks) do
      if block.tag == "Div" and block.identifier == "refs" then
        refs_div = block
        break
      end
    end
    if refs_div then
      doc.blocks = {refs_div}
    else
      doc.blocks = {}
    end
    return doc
  end

  if meta_to_bool(suppress_bib) then
    -- Remove the refs div from output
    local cleaned_blocks = pandoc.List()
    for _, block in ipairs(doc.blocks) do
      if not (block.tag == "Div" and block.identifier == "refs") then
        cleaned_blocks:insert(block)
      end
    end
    doc.blocks = cleaned_blocks
    return doc
  end

  return doc
end

--- Phase 6: Prevent external citeproc from re-processing.
local function prevent_reprocessing(doc)
  local sources = meta_list_to_strings(doc.meta.citation_group_sources)
  if not sources or #sources == 0 then
    return nil
  end

  -- Clear bibliography and references metadata so external --citeproc has nothing to process
  doc.meta.bibliography = nil
  doc.meta.references = nil

  return doc
end

return {
  {Pandoc = collect_and_inject_phantoms},  -- phases 1-2
  {Pandoc = run_citeproc_and_cleanup},     -- phases 3-4
  {Pandoc = handle_output_mode},           -- phase 5
  {Pandoc = prevent_reprocessing},         -- phase 6
}
