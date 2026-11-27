# ATGM report 
## Abstract
## Introduction 

## Data sets

Agent B is an email-drafting assistant built with LangChain and a local `qwen3:1.7b` model, with six tools. We generated scenarios with their own policy (allowed tools, recipients, date window, call order, call limit), ran Agent B on them and labelled every tool call with nine policy rules. Many sessions planned as normal ended up violating, because the small model often invents recipients, so we kept the labels based on what the agent really did.

| Set | Sessions | Violating | Tool calls | Flagged calls |
| --- | --- | --- | --- | --- |
| Training | 500 | 459 | 2,969 | 585 |
| Holdout (new scenarios) | 183 | 170 | 1,091 | 199 |

## System architecture (one short paragraph each)

**Online Isolation Forest**: For every tool call, the forest builds features that every agent has (duration, arguments, call number, gap to the previous call, success), updates one model per agent (Leveni et al., 2024) and sends the anomaly score to DSPOT.

**Sliding-window top-k monitoring**: Following Chen et al. (2017), the monitor counts violation types from the rule flags and alarms of other stages. The three Kafka partitions act as distributed nodes with a 10-minute window (20 slots of 30 s), k = 3 and ε = 5. In every slot it publishes the current top-k and its message counts.

**Binary session classifier**: The classifier turns each session into one feature vector (call counts, failures, gaps, argument features, call order, tool pairs) and trains a random forest and a logistic regression. We chose tree ensembles because they still tend to beat deep learning on medium-sized tabular data (Grinsztajn et al., 2022). A live scorer sends the violation probability of each finished session to the pipeline, and it reloads the model whenever the retraining component promotes a new one.

### Open-source tools and technologies


| Tool | Used for |
| --- | --- |
| Apache Kafka 3.8 | Message broker for all event, score and alarm topics |
| confluent-kafka (Python) | Kafka producers and consumers |
| PostgreSQL 16, psycopg | Analytics database and scenario ground truth |
| Grafana 11 | Dashboards |
| Docker, Docker Compose | Running the whole stack |
| uv | Python environments and dependencies |
| pytest | Unit tests |
| LangChain, langchain-ollama | Agent B | Agent and tool-calling loop |
| Ollama + Qwen3 (1.7B) | Agent B | Local LLM |
| CapyMOA | Online Isolation Forest | Online Isolation Forest implementation |
| NumPy | Online Isolation Forest | Feature vectors |
| scikit-learn | Binary session classifier | Random forest and logistic regression |
| joblib | Binary session classifier | Saving and loading models |

## Testing and experiments

We replayed the full dataset through the running stack and compared the stored scores with the labels.

| Component | Metric | Result |
| --- | --- | --- |
| Session classifier, random forest | Macro F1, unseen holdout (183) | **0.961** |
| Session classifier, logistic regression | Macro F1, unseen holdout (183) | 0.912 |
| Top-k monitoring | Messages vs. naive approach (replay) | 137 / 773 (17.7%) |
| Online Isolation Forest | Session AUC (max score) | 0.24 |

The random forest found all 13 compliant holdout sessions and missed only 2 of 170 violating ones. The top-k monitor needed less than a fifth of the naive messages. The forest ranked sessions poorly, because here violations are the majority (92%) and the rare compliant sessions look more unusual to an isolation-based detector. In short, unsupervised detection only works well when attacks are rare. We did not use the Agent A data for the classifier, because most of its violating labels were added only to balance the dataset.


## References

Chen, B., Lv, Z., Yu, X., & Liu, Y. (2017). Sliding window top-k monitoring over distributed data streams. *Data Science and Engineering, 2*, 289–300. https://doi.org/10.1007/s41019-017-0053-1

Greshake, K., Abdelnabi, S., Mishra, S., Endres, C., Holz, T., & Fritz, M. (2023). Not what you've signed up for: Compromising real-world LLM-integrated applications with indirect prompt injection. In *Proceedings of the 16th ACM Workshop on Artificial Intelligence and Security* (pp. 79–90). ACM.

Grinsztajn, L., Oyallon, E., & Varoquaux, G. (2022). Why do tree-based models still outperform deep learning on typical tabular data? In *Advances in Neural Information Processing Systems 35, Datasets and Benchmarks Track*.

Leveni, F., Weigert Cassales, G., Pfahringer, B., Bifet, A., & Boracchi, G. (2024). Online isolation forest. In *Proceedings of the 41st International Conference on Machine Learning* (PMLR 235).