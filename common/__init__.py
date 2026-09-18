"""
common — dependency-free leaf helpers shared by every concern package.

Purpose: hold the handful of values that BOTH the low layers (document_model,
knowledge_base) and the processing layer (pipeline) need — the sessions root
path and the UTC clock — so that a low layer never has to import `pipeline`
(and drag the whole processing stack, FastAPI included, into its import
graph) just to learn where sessions live. Nothing in here may import any
other first-party package; that is the whole point of the package.
"""
