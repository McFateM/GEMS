# Omeka adapter fixtures

These are small, fabricated item exports using documented Omeka API shapes,
not harvested collection records. Values and example.org URLs are test data.

- Classic item and `element_texts` shape:
  <https://omeka.readthedocs.io/en/latest/Reference/api/resources/items.html>
- Classic file properties, including `file_urls` and `original_filename`:
  <https://omeka.readthedocs.io/en/latest/Reference/api/resources/files.html>
- Omeka S JSON-LD resources:
  <https://omeka.org/s/docs/developer/api/>

Classic fixtures embed the documented file representations in `files_list`,
as expanded exports do. A raw Classic item API response contains only a file
listing link, and a raw S item may contain only media resource references.
The importer resolves S media references through their API during export.
Classic listing links still require expansion. API JSON is never treated as
an asset download.
