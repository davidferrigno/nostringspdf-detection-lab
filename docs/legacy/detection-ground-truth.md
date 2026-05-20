\# Detection Ground Truth Reference



Used for measuring detection quality on test PDFs.

Source: manual count by David Ferrigno, 2026-05-05.



\## NJ Marriage License (REG-77)



\### Page 1

\- Text fields: 64

\- Checkboxes: 34

\- Total: 98



\### Page 2

\- Text fields: 43

\- Checkboxes: 4

\- Total: 47



\### Combined

\- Text fields: 107

\- Checkboxes: 38

\- Total: 145



\### Reference detection results

\- Pre-12B heuristic: 153 detected (\~95% recall, \~5% false positive rate)

\- Post-12B heuristic: 74 detected (\~50% recall, false positives unknown)

\- iOS native: \~143 detected (\~99% recall on visual inspection)



\### Observed iOS misses

\- 2 SSN segment boxes on page 2 (visible in user screenshot)



\## sp-650

\- Total fields: 34

\- Includes 12 radio buttons across 5 groups



\## Eden Lane Nomination

\- Total fields: 21



\## Field Trip Form

\- Total fields: 19



\## I-9 (AcroForm)

\- Total fields: 130 via AcroForm widgets



\## Notes



The marriage license is a "dense form built from tables" — most fields

are inside a table-cell layout. Generic grid-suppression filters

break this form because the fields ARE in grid cells. Need a more

nuanced approach that distinguishes:

\- Structural grid lines (no field)

\- Grid cells with embedded labels and underline-style input zones

\- Grid cells where the cell itself is the input zone

