import re


# This function will extract pandoc-citeproc-style refs, like
# @ReferenceKey, from a given value.
def extract_refs(value):
    # :param: value Str The string you wish to extract references from
    # :return: list List of the reference keys (with @ removed).
    m = re.finditer("@([a-zA-Z0-9_])*", value)
    return [x.group() for x in m]


# Example:
# m = extract_refs("abc; hello @test;me @second one; and finally @three")
# m
