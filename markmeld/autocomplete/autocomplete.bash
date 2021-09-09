# begin markmeld bash completion
_mm_autocomplete()
{
   local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    opts=$(mm --autocomplete)
    COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
    return 0
}
complete -o nospace -F _mm_autocomplete mm
# end markmeld bash completion
