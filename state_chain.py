"""Model algorithms as a list of functions operating on a shared state object.


Installation
------------

:mod:`state_chain` is available on `GitHub`_ and on `PyPI`_::

    $ pip install state_chain

The version of :mod:`state_chain` documented here has been `tested`_ against
Python 3.6, 3.7 and 3.8 on Ubuntu.

:mod:`state_chain` is MIT-licensed.


.. _GitHub: https://github.com/AspenWeb/state_chain.py
.. _PyPI: https://pypi.python.org/pypi/state_chain
.. _tested: https://travis-ci.org/AspenWeb/state_chain.py


Tutorial
--------

This module provides an abstraction for implementing arbitrary algorithms as a
list of functions that operate on a shared state object. Algorithms defined
this way are easy to arbitrarily modify at run time, and they provide cascading
exception handling.

To get started, define a state type, for example:

    >>> from dataclasses import dataclass
    >>> from typing import Optional
    >>> @dataclass
    ... class State:
    ...     x: int = 0
    ...     y: int = 0
    ...     sum: int = 0
    ...     exception: Optional[Exception] = None
    ...


Then create a :class:`StateChain` object:

    >>> from state_chain import StateChain
    >>> chain = StateChain(State)


And add some functions to it:

    >>> @chain.add
    ... def foo(state: State):
    ...     state.x = 1
    ...
    >>> @chain.add
    ... def bar(state: State):
    ...     state.y = 2
    ...
    >>> @chain.add
    ... def bloo(state: State):
    ...     state.sum = state.x + state.y
    ...


As you can see, each function will receive the ``state`` object as its only argument.
Moreover you may have noticed that the functions don't return anything. Returning
a value isn't prohibited, but that value will be ignored by the :func:`~StateChain.run`
method.

Speaking of the run method, let's give it a go:

    >>> state = chain.run()
    >>> state.sum
    3

Okay, we have the expected sum!


Modifying a State Chain
+++++++++++++++++++++++

Let's define two more functions to add to the state chain:

    >>> def uh_oh(state: State):
    ...     if state.x == 0:
    ...         raise heck
    ...
    >>> def deal_with_it(state: State):
    ...     print("I am dealing with it!")
    ...     state.exception = None
    ...


and make a copy of the chain that we'll use later:

    >>> chain_copy = chain.copy()


Now let's interpolate the new functions into our state chain. Let's put the
``uh_oh`` function between ``bar`` and ``bloo``:

    >>> chain.add(uh_oh, position=chain.before('bloo'))      #doctest: +ELLIPSIS
    <function uh_oh ...>
    >>> chain.functions      #doctest: +ELLIPSIS
    (<function foo ...>, <function bar ...>, <function uh_oh ...>, <function bloo ...>)


Then let's add our exception handler after ``bloo``:

    >>> chain.add(deal_with_it, position=chain.after('bloo'), exception='required')      #doctest: +ELLIPSIS
    <function deal_with_it ...>
    >>> chain.functions      #doctest: +ELLIPSIS
    (<function foo ...>, <function bar ...>, <function uh_oh ...>, <function bloo ...>, <function deal_with_it ...>)


Just for kicks, let's remove the ``foo`` function while we're at it:

    >>> chain.remove('foo')
    >>> chain.functions      #doctest: +ELLIPSIS
    (<function bar ...>, <function uh_oh ...>, <function bloo ...>, <function deal_with_it ...>)


Note: when making extensive changes to a state chain, you can use the
:meth:`~StateChain.modify` method to rebuild the entire chain in a safe way.
We could have achieved the same result as above like so:

    >>> chain = (
    ...     chain_copy.modify()
    ...     .drop('foo')
    ...     .add('bar')
    ...     .add(uh_oh)
    ...     .add('bloo')
    ...     .add(deal_with_it, exception='required')
    ...     .end()
    ... )
    >>> chain.functions      #doctest: +ELLIPSIS
    (<function bar ...>, <function uh_oh ...>, <function bloo ...>, <function deal_with_it ...>)


This allows you to see exactly what your chain does and how it differs from the
original chain.

Either way, what happens when we run it?

    >>> state = chain.run()
    I am dealing with it!


Exception Handling
++++++++++++++++++

Whenever a function raises an exception, like ``uh_oh`` did in the example
above, :class:`~StateChain.run` captures the exception and assigns it to
``state.exception``. As long as this state attribute is not ``None``, any normal
function is skipped, and only exception handling functions get called. It's like
a fast-forward. So in our example ``deal_with_it`` got called, but ``bloo``
didn't, which is why ``sum`` is zero:

    >>> state.sum
    0


If we run without tripping the exception in ``uh_oh``, then we have the sum at
the end:

    >>> chain.run(State(x=5)).sum
    7


API Reference
-------------

"""

from collections import OrderedDict
from functools import partial
import opcode


__version__ = '1.5.0.dev0'


class FunctionNotFound(KeyError):
    """Used when a function is not found in a state_chain function list
    (subclasses :exc:`KeyError`).
    """
    def __str__(self):
        return "The function '{0}' isn't in this state chain.".format(*self.args)


class IncompleteModification(Exception):
    """
    Raised by :class:`ChainModifier.end` when one or more functions from the
    original chain has neither been dropped nor added to the modified chain.
    """
    def __str__(self):
        return (
            "The following functions have neither been dropped nor added to the "
            "modified chain: %r" % self.args
        )


_NO_PREVIOUS = object()

def _iter_with_previous(iterable):
    prev = _NO_PREVIOUS
    for o in iterable:
        yield o, prev
        prev = o


class StateChain:
    """Model an algorithm as a list of functions operating on a shared state.

    :param type state_type: the type of the state object
    :param functions: a sequence of functions in the order they are to be run
    :param bool raise_immediately: whether to re-raise exceptions immediately

    """

    __slots__ = (
        'state_type', 'raise_immediately', '_functions',
        '__dict__',
    )

    def __init__(self, state_type, functions=(), raise_immediately=False):
        self.state_type = state_type
        self._functions = ()
        self.add(*functions)
        self.raise_immediately = raise_immediately

    @property
    def functions(self):
        return tuple(func for func, _ in self._functions)

    def copy(self):
        """Returns a copy of this chain.
        """
        r = StateChain(self.state_type, raise_immediately=self.raise_immediately)
        r._functions = self._functions
        r.__dict__ = self.__dict__.copy()
        return r

    def run(self, state=None, raise_immediately=None, return_after=None):
        """Run through the functions in the :attr:`functions` list.

        :param State state: the initial state object for this run of the chain
            (`self.state_type()` is called to create an object if none is provided)

        :param bool raise_immediately: if not ``None``, will override any
            default for ``raise_immediately`` that was set in the constructor

        :param str return_after: if not ``None``, return after calling the function
            with this name

        :raises: :exc:`FunctionNotFound`, if there is no function named
            ``return_after``

        :returns: the ``state`` object

        For each function in the :attr:`functions` list, we look at the
        function's exception preference and at the current value of
        ``state.exception``. If ``state.exception`` is ``None``, then we skip
        any function whose exception preference is :obj:`'required'`, and if
        ``state.exception`` is *not* ``None`` then we only call functions whose
        exception preference is not :obj:`'unwanted'`. The upshot is that any
        function that raises an exception will cause us to fast-forward to the
        next exception-handling function in the list.

        Here are some further notes on exception handling:

         - If a function's exception preference is :attr:`'accepted'`, then that
           function will be called whether or not there is an exception being
           handled.

         - You should set ``state.exception = None`` when an exception has been
           handled. The chain run will resume normally from where it is (it
           won't backtrack to run the functions that were skipped during
           exception handling).

         - If an exception is raised by a function handling another exception,
           then ``state.exception`` is set to the new one and we look for the
           next exception handler.

         - If ``state.exception`` is not ``None`` after all functions have been
           run, then we re-raise it.

         - If ``raise_immediately`` evaluates to ``True`` (looking first at the
           ``raise_immediately`` argument and falling back to the chain's
           ``raise_immediately`` attribute), then we re-raise any exception
           immediately instead of fast-forwarding to the next exception handler.

         - When an exception occurs, the chain functions that handle it are
           called from inside the ``except:`` block, so you can access
           ``sys.exc_info`` (which contains the traceback).

        """

        if state is None:
            state = self.state_type()

        if raise_immediately is None:
            raise_immediately = self.raise_immediately

        if return_after is not None:
            return_after = self[return_after]

        if not hasattr(state, 'exception'):
            state.exception = None

        # The `for` loop in the `loop()` function below can be entered multiple
        # times since that function calls itself when an exception is raised.
        # If we looped over the `functions` list we'd be starting from the top
        # at each exception, and that's not what we want, so we use an iterator
        # instead to keep track of where we are in the state chain.
        functions_iter = _iter_with_previous(self._functions)

        def loop(in_except):
            for (function, exception_preference), (prev_func, _) in functions_iter:
                if prev_func is return_after:
                    break
                if in_except:
                    # Skip when function doesn't want exception but we have it.
                    if exception_preference == 'unwanted':
                        continue
                else:
                    # Skip when function wants exception but we don't have it.
                    if exception_preference == 'required':
                        continue
                try:
                    function(state)
                    if in_except and state.exception is None:
                        # exception is cleared, return to normal flow
                        return
                except Exception as e:
                    if raise_immediately:
                        raise
                    state.exception = e
                    loop(True)
                    if in_except:
                        # an exception occurred while we were handling another
                        # exception, but now it's been cleared, so we return to
                        # the normal flow
                        return
            if in_except:
                raise state.exception  # exception hasn't been handled, reraise

        loop(state.exception is not None)

        return state

    def __contains__(self, func_ref):
        if isinstance(func_ref, str):
            return func_ref in self.get_names()
        return any(func_ref is func for func, _ in self._functions)

    def __getitem__(self, name):
        """Return the function in the :attr:`functions` list named ``name``, or raise
        :exc:`FunctionNotFound`.

        >>> class State: pass
        >>> def foo(): pass
        >>> algo = StateChain(State, functions=[foo])
        >>> algo['foo'] is foo
        True
        >>> algo['bar']
        Traceback (most recent call last):
          ...
        state_chain.FunctionNotFound: The function 'bar' isn't in this state chain.

        """
        for candidate in self.functions:
            if candidate.__name__ == name:
                return candidate
        raise FunctionNotFound(name)

    def get_names(self):
        """Returns a list of the names of the functions in the :attr:`functions` list.
        """
        return [f.__name__ for f in self.functions]

    def add(self, *funcs, position=None, exception='unwanted'):
        """Insert functions into the chain.

        :param funcs: the function(s) to add to the chain

        :param int position: where to insert the function in the chain

        :param str exception: determines when this function will be run or skipped.
            The valid values are: 'unwanted', 'accepted', and 'required'.

        :raises: :exc:`TypeError` if an element of the ``funcs`` list isn't a callable

        >>> from types import SimpleNamespace
        >>> algo = StateChain(SimpleNamespace)
        >>> @algo.add
        ... def foo(): pass

        >>> @algo.add(position=0)
        ... def bar(): pass
        >>> algo.get_names()
        ['bar', 'foo']

        >>> @algo.add(position=algo.after('bar'), exception='accepted')
        ... def baz(): pass
        >>> algo.get_names()
        ['bar', 'baz', 'foo']

        >>> @algo.add(position=algo.before('bar'), exception='required')
        ... def bal(): pass
        >>> algo.get_names()
        ['bal', 'bar', 'baz', 'foo']

        Of course, the method doesn't have to be used as a decorator:

        >>> def bah(): pass
        >>> algo.add(bah, position=0)   #doctest: +ELLIPSIS
        <function bah at ...>
        >>> algo.get_names()
        ['bah', 'bal', 'bar', 'baz', 'foo']

        """
        if not funcs:
            return partial(self.add, position=position, exception=exception)
        for f in funcs:
            if not callable(f):
                raise TypeError("Not a function: " + repr(f))
        func_tuples = tuple((f, exception) for f in funcs)
        if position is None:
            self._functions += func_tuples
        else:
            self._functions = (
                self._functions[:position] + func_tuples + self._functions[position:]
            )
        if len(funcs) == 1:
            return funcs[0]

    def after(self, func_name):
        """Returns the chain position immediately after the function named `func_name`.
        """
        return self.functions.index(self[func_name]) + 1

    def before(self, func_name):
        """Returns the position of the function named `func_name` in this chain.
        """
        return self.functions.index(self[func_name])

    def remove(self, *names):
        """Remove the functions named ``name`` from the chain.

        :raises: :exc:`FunctionNotFound` if a name isn't found in the chain.

        """
        funcs = set(self[name] for name in names)
        self._functions = tuple(t for t in self._functions if t[0] not in funcs)

    def modify(self):
        """Returns a :class:`ChainModifier` object.
        """
        return ChainModifier(self)

    def debug(self, function):
        """Debug a specific function in the chain.

        :param function: a function object or name

        :raises: :exc:`FunctionNotFound` if the function isn't in this chain

        This method wraps the module-level function :func:`state_chain.debug`,
        adding two conveniences.

        First, calling this method not only returns a copy of the function with
        a breakpoint installed, it actually replaces the old function in the
        state chain with the copy. So you can do:

        >>> from types import SimpleNamespace
        >>> def foo(state):
        ...     pass
        ...
        >>> algo = StateChain(SimpleNamespace, functions=[foo])
        >>> algo.debug(foo)             #doctest: +ELLIPSIS
        <function foo at ...>
        >>> algo.run()                  #doctest: +SKIP
        (Pdb)

        Second, you can debug a function by passing its name:

        >>> algo = StateChain(SimpleNamespace, functions=[foo])
        >>> algo.debug('foo')           #doctest: +ELLIPSIS
        <function foo at ...>
        >>> algo.run()                  #doctest: +SKIP
        (Pdb)

        """
        if isinstance(function, str):
            function = self[function]
        try:
            i = self.functions.index(function)
        except ValueError:
            raise FunctionNotFound(function)
        debugging_function = debug(function)
        self._functions = (
            self._functions[:i] +
            ((debugging_function, self._functions[i][1]),) +
            self._functions[i+1:]
        )
        return debugging_function


class ChainModifier:
    """This class facilitates the safe modification of a :class:`StateChain`.

    Note that this class doesn't actually alter the given chain, it only returns
    a modified copy of that chain.

    """

    __slots__ = ('new_chain', 'old_functions')

    def __init__(self, chain):
        self.new_chain = StateChain(chain.state_type, raise_immediately=chain.raise_immediately)
        self.new_chain.__dict__ = chain.__dict__
        self.old_functions = OrderedDict((f.__name__, f) for f in chain.functions)

    def add(self, func_ref, exception='unwanted'):
        """Append a function to the modified chain.

        :param func_ref: the function to add, either a function object or the name
            of a function present in the original chain

        :param exception: see :meth:`StateChain.add`

        :raises: :exc:`FunctionNotFound` if `func_ref` is a string that doesn't
            match any function name from the original chain

        """
        if isinstance(func_ref, str):
            try:
                func = self.old_functions[func_ref]
            except KeyError:
                func = self.new_chain[func_ref]
        elif callable(func_ref):
            func = func_ref
        else:
            raise TypeError("expected a string or function, got " + repr(type(func_ref)))
        self.new_chain.add(func, exception=exception)
        self.old_functions.pop(func.__name__, None)
        return self

    def debug(self, func_ref, exception='unwanted'):
        """Same as :meth:`add`, but wraps the chain function with :func:`debug`.
        """
        self.add(func_ref, exception=exception)
        func = self.new_chain.functions[-1]
        self.new_chain.debug(func)
        return self

    def drop(self, func_name):
        """Skip a function present in the original chain.
        """
        try:
            self.old_functions.pop(func_name)
        except KeyError:
            raise FunctionNotFound(func_name)
        return self

    def end(self):
        """Returns the modified copy of the original chain.
        """
        if self.old_functions:
            raise IncompleteModification(list(self.old_functions.values()))
        return self.new_chain


# Debugging Helpers
# =================

def debug(function):
    """Given a function, return a copy of the function with a breakpoint
    immediately inside it.

    :param function function: a function object

    Okay! This is fun. :-)

    This is a decorator, because it takes a function and returns a function.
    But it would be useless in situations where you could actually decorate a
    function using the normal decorator syntax, because then you have the
    source code in front of you and you could just insert the breakpoint
    yourself. It's also pretty useless when you have a function object that
    you're about to call, because you can simply add a ``set_trace`` before the
    function call and then step into the function. No: this helper is only
    useful when you've got a function object that you want to debug, and you
    have neither the definition nor the call conveniently at hand. See the
    method :meth:`StateChain.debug` for an explanation of how this situation
    arises with the :mod:`state_chain` module.

    For our purposes here, it's enough to know that you can wrap any function:

    >>> def foo(bar, baz):
    ...     return bar + baz
    ...
    >>> func = debug(foo)

    And then calling the function will drop you into pdb:

    >>> func(1, 2)                  #doctest: +SKIP
    (Pdb)

    The fun part is how this is implemented: we dynamically modify the
    function's bytecode to insert the statements ``import pdb;
    pdb.set_trace()``.  Neat, huh? :-)

    """

    # Build bytecode for a set_trace call.
    # ====================================

    codes = ( ('LOAD_CONST', 0)
            , ('LOAD_CONST', None)
            , ('IMPORT_NAME', 'pdb')
            , ('STORE_GLOBAL', 'pdb')
            , ('LOAD_GLOBAL', 'pdb')
            , ('LOAD_ATTR', 'set_trace')
            , ('CALL_FUNCTION', 0)
            , ('POP_TOP', 0)
             )

    new_names = function.__code__.co_names
    new_consts = function.__code__.co_consts
    new_code = b''
    addr_pad = 0

    for name, arg in codes:
        # Since Python 3.6, all instructions use exactly two bytes.
        addr_pad += 2
        op = opcode.opmap[name]
        if op in opcode.hasconst:
            if arg not in new_consts:
                new_consts += (arg,)
            arg = new_consts.index(arg)
        elif op in opcode.hasname:
            if arg not in new_names:
                new_names += (arg,)
            arg = new_names.index(arg)
        if arg > 0xffffff:
            new_code += bytes((opcode.EXTENDED_ARG, (arg >> 24) & 0xff))
        if arg > 0xffff:
            new_code += bytes((opcode.EXTENDED_ARG, (arg >> 16) & 0xff))
        if arg > 0xff:
            new_code += bytes((opcode.EXTENDED_ARG, (arg >> 8) & 0xff))
            arg &= 0xff
        new_code += bytes((op, arg))

    # Insert our new bytecode in front of the old.
    # ============================================
    # Loop over old_code and append it to new_code, fixing up absolute jump
    # references along the way. Adapted from `dis._unpack_opargs()`.

    old_code = function.__code__.co_code
    i = 0
    extended_arg = 0
    for i in range(0, len(old_code), 2):
        # In Python 3, index access on a bytestring returns an int.
        op = old_code[i]
        arg = old_code[i+1] | extended_arg
        if op == opcode.EXTENDED_ARG:
            extended_arg = arg << 8
            continue
        else:
            extended_arg = 0
        if op in opcode.hasjabs:
            arg += addr_pad
        if arg > 0xffffff:
            new_code += bytes((opcode.EXTENDED_ARG, (arg >> 24) & 0xff))
        if arg > 0xffff:
            new_code += bytes((opcode.EXTENDED_ARG, (arg >> 16) & 0xff))
        if arg > 0xff:
            new_code += bytes((opcode.EXTENDED_ARG, (arg >> 8) & 0xff))
            arg &= 0xff
        new_code += bytes((op, arg))

    # Fix up the line number table.
    # =============================
    # See https://github.com/python/cpython/blob/3.8/Objects/lnotab_notes.txt

    old = function.__code__.co_lnotab
    new_lnotab = bytes((addr_pad, 0)) + old

    # Now construct new code and function objects.
    # ============================================
    # See Objects/codeobject.c in Python source.

    if hasattr(function.__code__, 'replace'):
        # Python >= 3.8
        new_code = function.__code__.replace(
            co_code=new_code,
            co_consts=new_consts,
            co_names=new_names,
            co_lnotab=new_lnotab,
        )
    else:
        new_code = type(function.__code__)(
            function.__code__.co_argcount,
            function.__code__.co_kwonlyargcount,
            function.__code__.co_nlocals,
            function.__code__.co_stacksize,
            function.__code__.co_flags,
            new_code,
            new_consts,
            new_names,
            function.__code__.co_varnames,
            function.__code__.co_filename,
            function.__code__.co_name,
            function.__code__.co_firstlineno,
            new_lnotab,
            function.__code__.co_freevars,
            function.__code__.co_cellvars,
        )
    new_function = type(function)(
        new_code,
        function.__globals__,
        function.__name__,
        function.__defaults__,
        function.__closure__,
    )

    return new_function
