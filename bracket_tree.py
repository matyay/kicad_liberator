"""
Reader and writer module for so called "bracket tree" file. Can read, parse
and write KiCad files such as .kicad_pcb, .kicad_mod, fp-lib-table and
sym-lib-table.
"""
from collections import namedtuple
from io import StringIO

# =============================================================================


class Node(object):
    """
    Represents a single tree node. Holds reference to its parent and children.
    The children order is important! Children objects are either another Node
    instances or strings (attributes).
    """

    def __init__(self, parent, keyword, children = None):
        self.parent  = parent
        self.keyword = keyword
        self.child   = children if children is not None else []

    @property
    def children(self):
        """
        Returns all children nodes.
        """
        return [c for c in self.child if isinstance(c, Node)]

    @property
    def attributes(self):
        """
        Returns all attributes.
        """
        return [c for c in self.child if isinstance(c, str)]

    def add(self, child):
        """
        Adds a new child
        """
        self.child.append(child)

    def remove(self, child):
        """
        Removes a child
        """
        assert child in self.child
        self.child.remove(child)

    def replace(self, child, new_child):
        """
        Replaces a child
        """
        assert child in self.child

        idx = self.child.index(child)
        self.child[idx] = new_child

    def findall(self, keyword):
        """
        Finds all child nodes with given keyword. Returns a list of them.
        """
        return [c for c in self.children if c.keyword == keyword]

    def find(self, keyword):
        """
        Finds a first child node with given keyword. Returns None if not found.
        """
        res = self.findall(keyword)

        if len(res) > 0:
            return res[0]

        return None

    def has(self, attr):
        """
        Returns True if the node has the given attribute
        """
        return attr in self.attributes

# =============================================================================

TOKEN_WORD      = 0
TOKEN_KEYWORD   = 1
TOKEN_OPEN      = 2
TOKEN_CLOSE     = 3

Token = namedtuple("Token", "type data")

# =============================================================================


def tokenize(data):
    """
    Tokenize a string representing the "bracket tree".
    """

    ios = StringIO(data)
    tokens = []

    quote = False

    word_token = TOKEN_KEYWORD
    word = ""

    # Process text
    while True:

        # Read a single character
        c = ios.read(1)
        if c == "":
            break

        # Begin quote
        if not quote and c == "\"":
            quote = True
            continue

        # End quote, emit the quoted word
        if quote and c == "\"":
            quote = False

            tokens.append(Token(word_token, word))
            word_token = TOKEN_WORD
            word = ""
            continue
       
        # Inside quote
        if quote:
            word += c

        # Outside a quote
        else:

            # "(" or ")"
            if c in ["(", ")"]:

                # In the middle of a word
                if len(word):
                    tokens.append(Token(word_token, word))
                    word = ""

                # Emit the token
                tokens.append(Token(
                    TOKEN_OPEN if c == "(" else TOKEN_CLOSE,
                    c
                    ))

                word_token = TOKEN_KEYWORD if c == "(" else TOKEN_WORD

            # Skip white space but only when no non-space
            # characters were recorded.
            elif c.isspace():

                if len(word):
                    tokens.append(Token(word_token, word))
                    word_token = TOKEN_WORD
                    word = ""

            # Append to word
            else:
                word += c

    return tokens


def parse(data):
    """
    Parse a string representing the "bracket tree".
    """

    # Tokenize
    tokens = tokenize(data)

    # Build the tree
    root  = None
    node  = None
    stack = []

    for token in tokens:

        # Skip this one as the keyword token serves the purpose
        # of beginning of a new node.
        if token.type == TOKEN_OPEN:
            pass

        # Keyword, add a new node
        elif token.type == TOKEN_KEYWORD:
            stack.append(node)

            parent = node
            node = Node(parent, token.data)

            if parent:
                parent.child.append(node)
            else:
                assert root is None
                root = node

        # Append attributes to the current node
        elif token.type == TOKEN_WORD:
            node.child.append(token.data)

        # Pop a node from the stack
        elif token.type == TOKEN_CLOSE:
            node = stack.pop()

    # Check
    assert len(stack) == 0

    # Return the root
    return root


def load(file_name):
    """
    Loads and parses a file with the "bracket tree" definition.
    """
    
    with open(file_name, "r") as fp:
        return parse(fp.read())

# =============================================================================


def dump(tree):
    """
    Converts a "bracket tree" to a string representation.
    """

    # Convert the tree to tokens
    def node_to_tokens(node, tokens):
        tokens.append(Token(TOKEN_OPEN, "("))
        tokens.append(Token(TOKEN_KEYWORD, node.keyword))

        for child in node.child:
            if isinstance(child, str):
                tokens.append(Token(TOKEN_WORD, child))
            if isinstance(child, Node):
                node_to_tokens(child, tokens)

        tokens.append(Token(TOKEN_CLOSE, ")"))
    
    # Start from the root, do the rest recursively.
    tokens = []
    node_to_tokens(tree, tokens)

    # Convert tokens to string
    string  = ""
    indent  = 0
    newline = False
    for token in tokens:
        
        if token.type == TOKEN_OPEN:
            string += "\n" + " " * indent
            string += "("
            newline = False

        elif token.type == TOKEN_KEYWORD:
            word = token.data
            if "(" in word or ")" in word or " " in word or len(word) == 0:
                word = "\"" + word + "\""
            string += word
            indent += 2

        elif token.type == TOKEN_WORD:
            word = token.data
            if "(" in word or ")" in word or " " in word or len(word) == 0:
                word = "\"" + word + "\""
            string += " " + word

        elif token.type == TOKEN_CLOSE:
            indent -= 2
            if newline:
                string += "\n" + " " * indent + ")"
            else:
                string += ")"
            newline = True

    return string


def save(file_name, tree):
    """
    Dumps a "bracket tree" tree representation to a file.
    """

    with open(file_name, "w") as fp:
        text = dump(tree)
        fp.write(text)

