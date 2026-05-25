# Refgate Design Draft

Refgate turns reference management into an explicit gate before bibliography
changes are accepted.

Pipeline:

```text
query -> discovery -> candidate records -> deterministic resolver
      -> authority record -> official BibTeX or manual fallback
      -> lockfile -> manuscript artifact audit -> report
```

Primary invariant:

```text
official record verification != official BibTeX export verification
```

The lockfile is the source of truth. Markdown reports are derived artifacts.

Source adapters must keep discovery evidence separate from final authority
evidence. The arXiv adapter is authoritative only for the preprint record. If a
query names a preferred official venue but the arXiv record has no DOI or
journal reference, Refgate reports `official_record_pending` instead of treating
the preprint as a final publication authority.

Manual arXiv BibTeX fallback uses `arxiv_manual_normalized`. It must not be
stored or reported as `official_export`.

The integrated `audit` command checks bibliography provenance, manuscript
citation keys, and claim-to-source TSV status in frozen mode. Network refresh is
kept out of the default audit path.
