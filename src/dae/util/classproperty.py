
class classproperty:
	"""Read-only class-level property.

	Replaces the `@classmethod` + `@property` chaining, which stopped working in Python 3.13
	(it now returns a bound method instead of the value)."""

	def __init__(self, fget):
		self.fget = fget
		self.__doc__ = fget.__doc__
		self.__isabstractmethod__ = getattr(fget, "__isabstractmethod__", False)

	def __get__(self, instance, owner = None):
		if owner is None:
			owner = type(instance)
		
		return self.fget(owner)
