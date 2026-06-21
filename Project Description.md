## Objective
Evaluate [headroom](https://headroom-docs.vercel.app/docs) and its claims of 100% accuracy with 87% token reduction over a number of text data - JSON and Plain text.

## Tech stack
Python CLI, AWS Bedrock boto3 calls, Rich visualizations of test results.
## Requirements
1. Headroom Features to be tested:
	1. `compress()` and  `retrieve()` APIs.
	2. LLMLingua, TextCompressor for plain text. [Reference](https://headroom-docs.vercel.app/docs/text-and-logs)
	3. SmartCrusher for JSON. [Reference](https://headroom-docs.vercel.app/docs/smart-crusher)
	4. Ability ensure 100% accuracy with compression on very large, complex prompts (~300-500 word prompts) against the same data and prompt without compression
	5. Simulation mode for trial and error. Limit to metrics - Tokens before, after, saved, transforms applied and waste signals.  [Ref](https://headroom-docs.vercel.app/docs/simulation)
2. If LLM calls are involved in a run, capture token stats from both headroom results and LLM response.
3. Rich data capture for each run. Simulation or against LLM API.
4. CLI to be config driven. All configuration params supported by every headroom feature being tested must be present in in the CLI config. Each run must re-read the config to check for changes between runs. [API and config reference](https://headroom-docs.vercel.app/docs/api-reference)
