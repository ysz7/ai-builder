# Fixture: a deliberately mis-annotated project

Every static gate check has exactly one instance here. It is not a runnable service and is
not meant to be one -- `app/broken.py` does not even parse. Its whole job is to fail, and
to prove the failures come back addressed precisely enough that a repair prompt can be
written from the diagnostics alone.

Do not tidy anything in this directory. Each defect is load-bearing.
