# Timeline and project description

## General project rules

OST+SM joint projects plan and milestones:

- Project topics are chosen and solved by 5-member teams.
  - Team formation deadline: **Oct 4, 2026**.
  - Project selection deadline: **Oct 4, 2026**. Max points deduction if this deadline is missed (-10%).
- System architecture and per team member work plan - Deadline: **Oct 19, 2026**. Sooner the better. Revise with the project supervisor. Significant point deductions if this deadline is missed (-15%).
- Early project submission deadline will be **Nov 26, 2026 (12:00 CET)**. We will organize the theoretical part of both exams (SM & OST) in December for candidates submitting their projects by this deadline on the first submitted, first served basis. Submissions only via Canvas assignments.
- Early project defenses in the Nov 30 - Dec 4 week.
- Late project submission deadline will be **Dec 6, 2026 (12:00 CET)**.

Minimum project implementations include at least the following elements for a passing grade (and meaningfully more for a higher grade):

- 2 different input datasets utilized - if feasible.
- 1 streaming system included in the system architecture.
- 2 stream processing stages developed by each team member doing the project in the SM course. Identify interesting algorithms in relevant scientific papers and implement and integrate such algorithms for a higher grade!
- 1 data storage tech where the input data stream or its aggregate is persisted.
- 1 batch processing stage trained and utilized on 'static' data in the data store.
- 1 visualization solution. Each team member creates at least one (meaningful) dashboard with at least 2 graphs included.
- Reference research papers (conference or journal) and implement the solutions or their derivatives for higher grades (4 and 5) in the SM course.

Project descriptions are provided by the course teams and include at least the following

- Title and short description.
- List of datasets to be used.
- Data analysis and flow stages diagram - might include the names of technologies used to implement each analytics.
  - Batch analytics.
  - Stream mining transformations.
- Deployment diagram showing the actual deployment of each utilised technology and data source on Docker containers or similar.
- List of open-source tools and technologies which must be included in the project.
- Useful references to papers and online resources if any.

## Project submission

The project submission will consist of the following elements:

- Github repository for the code.
- Github (or other) repo for the data (unless otherwise instructed).
- A short-ish project report describing the system. The report should be integrated into the Github repository - it must contain the same elements in that case as well (see details below). Alternatively, and on request the report can be edited in Overleaf (LNCS template format).
- A **max&#x20;**&#x31;0-slide PPT focusing on the system architecture and key contributions. This will be presented during the project presentations in the last two weeks of the semester. The structure closely follows the report structure. Additionally:
  - The PPT includes a well-defined description of duties performed by project team members, i.e. the team members tell us who did which part of the project. This will allow the course team to separately grade the team members, i.e. not all team members get the same grades in every case.

## Project Documentation

The project documentation is submitted either in Github, or as a separate Overleaf document in the LNCS template on Overleaf which is available here: [https://www.overleaf.com/latex/templates/springer-lecture-notes-in-computer-science/kzwwpvhwnvfj](https://www.overleaf.com/latex/templates/springer-lecture-notes-in-computer-science/kzwwpvhwnvfj)

- It contains the following elements/sections:
  - Structured abstract (up to 200 words). Background, goal, method, results, impact.
  - Introduction (up to 1 pp). Includes a references to relevant scientific papers, standards and technologies.
  - Data sets utilised (up to 1 pp).
  - System architecture (2 pp).
  - Testing/experiments (2 pp).
  - References. At least 10 entries (but max 15).
- The documentation will be written in English and checked for grammar errors by the team members (or third parties helping the team members). Very bad English will not be accepted, so-so bad English will affect the points received.
- The references will be listed in the APA or Harvard format. There will be at least 10 relevant references, but not morem than 15 and which are not equal to the course materials and/or books. Find similar conference/journal papers and/or project reports and refer to them.
- The age of the references should not be older than 10 years. 2-3 exceptions are accepted if they are highly relevant and therefore necessary.
- The documentation will be shared with the course professors on Overleaf or Github and not in PDF or other non-shared document format.

## Topic

### T7 (Oumaima): Agent Tool-Use Guardrail Monitor (ATGM)

- **Description:** Build a monitoring layer around two simple LLM-based agents, each with a different toolset (e.g., one with calculator/file-read tools, another with web-search/email-draft tools), that logs every tool call in real time and checks it against policy. The team simulates normal and adversarial (prompt-injected) runs for both agents, detects both single-call misuse and out-of-order tool-call sequences, distinguishes legitimate behavior changes (e.g., a new tool being added) from real attacks, and improves detection through a periodic feedback/retraining loop.
- **Team size:** 5
- **Mentored by:** Oumaima Araar
- **List of datasets to be used:&#x20;**&#x53;elf-generated logs from two agent deployments with different toolsets, covering both normal operation and adversarial (prompt-injected) runs.
- **Open-source technologies to be used:** Kafka for real-time log ingest, LangChain/CrewAI for both monitored agents, scikit-learn for classification, River (or similar) for sequence modeling and drift detection, InfluxDB/PostgreSQL for storage, Grafana for visualization, Docker/Kubernetes for deployment.
- **Batch processing task(s):**
  - Batch 1: Train a binary classifier (policy-compliant vs. violating tool-call sequence).
  - Batch 2: Train a fine-grained classifier of violation type (unauthorized tool call, unsafe arguments, out-of-order sequence).
  - Batch 3: Learn a sequence model (e.g., a Markov chain) of each agent's normal tool-call order, to catch order-based violations that per-call checks miss.
  - Batch 4: Periodically retrain all models using newly reviewed logs from the feedback loop.
- **Example stream mining pipelines:**
  - Pipeline 1: Real-time allow-list policy check on each tool call.
  - Pipeline 2: Real-time ML classification of tool-call sequences, flag deviations.
  - Pipeline 3: Real-time sequence-order check against the learned Markov model, flag out-of-order violations.
  - Pipeline 4: Maintain a rolling count of violations per tool/agent and alert on spikes.
  - Pipeline 5: Distinguish legitimate behavior drift (e.g., a newly added tool) from an actual attack, flagging only unexplained deviations for review.
  - Pipeline 6: Route flagged/uncertain sessions to a review queue and feed reviewed labels into the next retraining cycle.
- **Visualization:** Per-agent live dashboard of the tool-call stream, flagged violations by type, order-violation alerts, drift-vs-attack indicators, review-queue status.
