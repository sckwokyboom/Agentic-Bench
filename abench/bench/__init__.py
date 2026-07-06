"""Universal benchmark layer: adapters that feed benchmark instances into the
existing abench run pipeline. The built-in adapters self-register when the
package is imported (wired in a later task)."""
from . import registry  # noqa: F401
from . import smoke  # noqa: F401  (registers the smoke adapter on import)
from . import javabench  # noqa: F401  (registers the javabench adapter on import)
from . import swebench_java  # noqa: F401  (registers the swebench-java adapter on import)
