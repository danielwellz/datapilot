"""Synthetic, deterministic sales data for development, tests and demos.

``calendar`` decides how many orders fall on each day, ``reference`` holds the
fixed lists (countries, categories, names), ``generator`` turns a seed into
rows, and ``loader`` streams those rows into PostgreSQL with COPY.
"""
