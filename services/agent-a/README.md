# Agent A

Agent A (statistics/calculator agent) is developed in its own repository:
**[datalens-agent](https://github.com/Agent-Tool-Use-Guardrail-Monitor-ATGM/datalens-agent)** (owners: Maxim, Asmar).

It publishes its tool-call events to the `tool-calls.A` Kafka topic of this platform. To reach Kafka at
`kafka:9092`, its compose file joins the shared `atgm` network (see the main README,
"Connecting a service from another repository").
