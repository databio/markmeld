import re

def extract_refs(value: str) -> list:
    """
    This is a custom jinja filter that will find and return pandoc-citeproc-style refs, like
    "@ReferenceKey", from a given string.

    :param: value Str The string you wish to extract references from
    :return: list List of the reference keys (with @ removed).
    """
    # Example:
    # m = extract_refs("abc; hello @test;me @second one; and finally @three")
    # m  # returns ['test', 'second', 'three']

    m = re.finditer("@([a-zA-Z0-9_])*", value)
    return [x.group() for x in m]
