-- debugging function. Use it to dump a nested dict
function dump(o)
   if type(o) == 'table' then
      local s = '{ '
      for k,v in pairs(o) do
         if type(k) ~= 'number' then k = '"'..k..'"' end
         s = s .. '['..k..'] = ' .. dump(v) .. ','
      end
      return s .. '} '
   else
      return tostring(o)
   end
end

if FORMAT:match 'latex' then
  return {
    -- Pass 1: Figure handler (pandoc 3+)
    -- Pandoc 3 wraps images in Figure blocks. We must replace the
    -- entire Figure to avoid nesting figure*/wrapfigure inside figure.
    {
      Figure = function(fig)
        local img = nil
        fig:walk({
          Image = function(elem)
            if elem.attributes.fullwidth or elem.attributes.wrap then
              img = elem
            end
          end
        })
        if not img then return nil end
        print("Figczar processing: " .. img.src)

        -- Use pandoc.write to render caption inlines to LaTeX,
        -- preserving bold, italics, citations, and other formatting.
        local caption_latex = pandoc.write(
          pandoc.Pandoc({pandoc.Plain(fig.caption.long[1].content)}), 'latex'
        ):gsub('%s+$', '')

        if img.attributes.fullwidth then
          local latex = [[\setlength{\intextsep}{2pt}\setlength{\columnsep}{8pt}\begin{figure*}]]
            .. '[' .. img.attributes.fullwidth .. ']'
            .. [[\centering\includegraphics{]] .. img.src .. [[}]]
            .. [[\caption{]] .. caption_latex .. [[}]]
            .. [[\vspace{-5pt}\end{figure*}]]
          return pandoc.RawBlock('latex', latex)

        elseif img.attributes.wrap then
          local wrappos = img.attributes.wrappos or "R"
          local latex = [[\setlength{\intextsep}{2pt}\setlength{\columnsep}{8pt}\begin{wrapfigure}{]]
            .. wrappos .. [[}{]] .. img.attributes.wrap .. '}'
            .. [[\centering\includegraphics{]] .. img.src .. [[}]]
            .. [[\caption{]] .. caption_latex .. [[}]]
            .. [[\vspace{0pt}\end{wrapfigure}]]
          return pandoc.RawBlock('latex', latex)
        end
      end
    },

    -- Pass 2: Image handler (pandoc 2 fallback)
    -- In pandoc 2, there is no Figure element; images are bare Para [Image ...].
    -- This pass only fires for images that were NOT already handled by pass 1.
    {
      Image = function(elem)
        print("Figczar processing: " .. elem.src)
        if elem.attributes.wrap then
          local wrappos
          if elem.attributes.wrappos then
            wrappos = elem.attributes.wrappos
          else
            wrappos = "R"
          end
          local latex_begin=[[\setlength{\intextsep}{2pt}\setlength{\columnsep}{8pt}\begin{wrapfigure}{]] .. wrappos ..[[}{]] .. elem.attributes.wrap .. '}'
          local latex_fig = [[\centering\includegraphics{]] .. elem.src .. [[}\caption{]]
          local latex_end = [[}\vspace{0pt}\end{wrapfigure}]]
          rval = elem.caption
          table.insert(rval, 1, pandoc.RawInline('latex', latex_fig))
          table.insert(rval, 1, pandoc.RawInline('latex', latex_begin))
          table.insert(rval, pandoc.RawInline('latex', latex_end))
          return rval
        elseif elem.attributes.fullwidth then
          local latex_begin
          latex_begin=[[\setlength{\intextsep}{2pt}\setlength{\columnsep}{8pt}\begin{figure*}]] .. '[' .. elem.attributes.fullwidth .. ']'
          local latex_fig = [[\centering\includegraphics{]] .. elem.src .. [[}\caption{]]
          local latex_end = [[}\vspace{-5pt}\end{figure*}]]
          rval = elem.caption
          table.insert(rval, 1, pandoc.RawInline('latex', latex_fig))
          table.insert(rval, 1, pandoc.RawInline('latex', latex_begin))
          table.insert(rval, pandoc.RawInline('latex', latex_end))
          return rval
        else
          return elem
        end
      end
    }
  }
end
