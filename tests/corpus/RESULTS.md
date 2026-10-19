# Corpus results

48 nets from 11 sources (see `manifest.json`), budget 20000 markings, compared with CPN Tools 4.0.1. Regenerate with `python tests/corpus/corpus.py run --oracle`.

| Outcome | Nets |
|---|---|
| explored | 12 |
| over budget | 17 |
| refused | 19 |

Against CPN Tools: 9 agree, 2 contained, 1 rejected by CPN Tools.

| Net | Source | Outcome | Detail |
|---|---|---|---|
| cpnbook/2-1DeterministicProtocol.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | explored | 31 nodes, 30 arcs, 1 dead; CPN Tools: agree |
| cpnbook/2-10NondeterministicProtocol.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | over budget | 20000 nodes, 100310 arcs, 62 dead |
| cpnbook/3-1UnionRecord.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | over budget | 20000 nodes, 116577 arcs, 156 dead |
| cpnbook/3-7Queues.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | over budget | 20000 nodes, 91852 arcs, 27 dead |
| cpnbook/3-18Functions.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | over budget | 20000 nodes, 100310 arcs, 62 dead |
| cpnbook/3-19Polymorphic.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | over budget | 20000 nodes, 100310 arcs, 62 dead |
| cpnbook/3-20Recursion.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | over budget | 20000 nodes, 148143 arcs, 13 dead |
| cpnbook/5-1HierarhicalProtocol.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | over budget | 20000 nodes, 100310 arcs, 62 dead |
| cpnbook/5-8Instances.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | over budget | 20000 nodes, 100310 arcs, 62 dead |
| cpnbook/5-19TwoReceivers.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | over budget | 20000 nodes, 98464 arcs, 1011 dead |
| cpnbook/5-24TwoReceivers.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | over budget | 20000 nodes, 98456 arcs, 1013 dead |
| cpnbook/5-30MultipleReceivers.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | over budget | 20000 nodes, 89837 arcs, 4032 dead |
| cpnbook/7-2LimitProtocol.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | explored | 13215 nodes, 52784 arcs, 1 dead; CPN Tools: agree |
| cpnbook/10-1TimedProtocol.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | over budget | 20000 nodes, 23099 arcs, 2752 dead, timed |
| cpnbook/10-19TimedStateSpaces.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | over budget | 20000 nodes, 31513 arcs, 6089 dead, timed |
| cpnbook/12-1PerformanceProtocol.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | refused | DataPacket Arrives: output arc: unbound name 'IntInf.toInt' |
| cpnbook/12-2-6PerformanceProtocol.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | refused | DataPacket Arrives: output arc: unbound name 'IntInf.toInt' |
| cpnbook/12-7PerformanceProtocol.cpn | Jensen & Kristensen, Coloured Petri Nets (2009): the book's models | refused | DataPacket Arrives: output arc: unbound name 'IntInf.toInt' |
| dynamic-coloured-petri-net/Pn model one.cpn | battery-powered system | over budget | 20000 nodes, 26583 arcs, 188 dead |
| dynamic-coloured-petri-net/Pn model two.cpn | battery-powered system | over budget | 20000 nodes, 27187 arcs, 7 dead, timed |
| dynamic-coloured-petri-net/pn model three.cpn | battery-powered system | over budget | 20000 nodes, 25717 arcs, 10021 dead, timed |
| BuildIT-Business-Process-and-Workflow-Management/Scenario-One.cpn | equipment rental workflow | over budget | 20000 nodes, 35056 arcs, 3596 dead, timed |
| BuildIT-Business-Process-and-Workflow-Management/Scenario-Two.cpn | equipment rental workflow | refused | assignrandomarrivaltime: time inscription: discrete draws a random value; a net that does has no deterministic occurrence graph and is not supported |
| BuildIT-Business-Process-and-Workflow-Management/Scenario-Three-A.cpn | equipment rental workflow | refused | assignrandomarrivaltime: time inscription: discrete draws a random value; a net that does has no deterministic occurrence graph and is not supported |
| BuildIT-Business-Process-and-Workflow-Management/Scenario-Three-B.cpn | equipment rental workflow | refused | assignrandomarrivaltime: time inscription: discrete draws a random value; a net that does has no deterministic occurrence graph and is not supported |
| SED_Projeto02/modelo_cpn_tools.cpn | electric vehicle charging station | explored | 66 nodes, 246 arcs, 0 dead; CPN Tools: agree |
| PetriNets_CPN_Workflow/ScrumWorkflow2.cpn | Scrum sprint workflow | refused | Estimate tasks: output arc: discrete draws a random value; a net that does has no deterministic occurrence graph and is not supported |
| sdn-coloredpetrinet-model/finalwork.cpn | software-defined networking | refused | R_NetDevInfor: code segment: unbound name 'ConnManagementLayer.openConnection' |
| advanced-topics-cs/ID1179034-part1.cpn | course assignment (UniPd) | refused | initial marking '15`()@0.0': model time must be an integer, not 0.0 (real-time nets are not supported) |
| advanced-topics-cs/ID1179034-part2.cpn | course assignment (UniPd) | refused | initial marking '15`()@0.0': model time must be an integer, not 0.0 (real-time nets are not supported) |
| system_engineering/testProject.cpn | container terminal simulation | refused | New Page/Ship: an arc without an inscription; CPN Tools does not compile the transition (it can never occur there) -- give the arc its inscription |
| system_engineering/project2.cpn | container terminal simulation | refused | startSailing: time inscription: discrete draws a random value; a net that does has no deterministic occurrence graph and is not supported |
| system_engineering/project3.cpn | container terminal simulation | refused | startSailing: time inscription: discrete draws a random value; a net that does has no deterministic occurrence graph and is not supported |
| system_engineering/project5.cpn | container terminal simulation | refused | startSailing: time inscription: discrete draws a random value; a net that does has no deterministic occurrence graph and is not supported |
| system_engineering/projectWithSenario.cpn | container terminal simulation | refused | startSailing: time inscription: discrete draws a random value; a net that does has no deterministic occurrence graph and is not supported |
| db-net-eip-patterns/aggregator.cpn | enterprise integration patterns (db-net extension) | explored | 1 nodes, 0 arcs, 1 dead; CPN Tools: agree |
| db-net-eip-patterns/content_enricher.cpn | enterprise integration patterns (db-net extension) | explored | 8 nodes, 12 arcs, 1 dead; CPN Tools: agree |
| db-net-eip-patterns/delayer.cpn | enterprise integration patterns (db-net extension) | explored | 11 nodes, 10 arcs, 10 dead, timed; CPN Tools: contained |
| db-net-eip-patterns/message_translator.cpn | enterprise integration patterns (db-net extension) | explored | 2 nodes, 1 arcs, 1 dead; CPN Tools: agree |
| db-net-eip-patterns/splitter.cpn | enterprise integration patterns (db-net extension) | refused | guard '[obj !=nil]': '=' cannot start an expression |
| db-net-eip-patterns/throttler.cpn | enterprise integration patterns (db-net extension) | refused | get message: output arc: exponential draws a random value; a net that does has no deterministic occurrence graph and is not supported |
| db-net-eip-patterns/resequencer.cpn | enterprise integration patterns (db-net extension) | explored | 1 nodes, 0 arcs, 1 dead; CPN Tools: agree |
| publish-subscribe/publish-subscribe.cpn | publish-subscribe, generated from UML | refused | Subscription/ASG_bought_0: an arc without an inscription; CPN Tools does not compile the transition (it can never occur there) -- give the arc its inscription |
| CPNpy/dining_philosophers.cpn | CPNpy examples | explored | 4 nodes, 6 arcs, 0 dead; CPN Tools: rejected by CPN Tools |
| CPNpy/guarded_choice.cpn | CPNpy examples | explored | 32 nodes, 80 arcs, 1 dead; CPN Tools: agree |
| CPNpy/simple_transfer.cpn | CPNpy examples | explored | 6 nodes, 7 arcs, 1 dead; CPN Tools: agree |
| CPNpy/timed_conveyor.cpn | CPNpy examples | explored | 8 nodes, 12 arcs, 1 dead, timed; CPN Tools: contained |
| CPNpy/plane_boarding.cpn | CPNpy examples | refused | myNet/Move up: time inscription '@++exponential(8.0)' is not supported (integer delays @+d only) |
