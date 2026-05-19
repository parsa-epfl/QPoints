# Direction Misprediction Report

## Result

TAGE restoration significantly reduces conditional direction mispredictions over the first `100000` committed instructions from `snapshot_0`.

- cold run: `697 / 8049` conditional mispredictions
- restored run: `62 / 7509` conditional mispredictions
- reduction: `635` fewer conditional mispredictions
- reduction percentage: `91.10%`

Conditional direction accuracy:
- cold run: `91.34%`
- restored run: `99.17%`
- gain: `7.83` percentage points

## Provider counters

Cold run:
- `longestMatchProviderCorrect = 4966`
- `longestMatchProviderWrong = 29`
- `bimodalProviderCorrect = 1551`
- `bimodalProviderWrong = 626`

Restored run:
- `longestMatchProviderCorrect = 4257`
- `longestMatchProviderWrong = 14`
- `bimodalProviderCorrect = 2878`
- `bimodalProviderWrong = 21`

Most of the cold-start pain disappears after restoration. The most visible change is in the bimodal fallback path:
- `bimodalProviderWrong`: `626` -> `21`

## Interpretation

The restored run is much closer to the intended warmed TAGE behavior immediately after checkpoint restore. This validation package is the compact before/after record for the current committed restoration implementation.
