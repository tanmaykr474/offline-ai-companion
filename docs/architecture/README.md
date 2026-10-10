# Nova architecture

nova-architecture.svg is the editable diagram source. nova-architecture.png is the
exported image, also embedded in the hackathon PPTX. Copies live in
docs/hackathon-presentation to keep the evaluation package self-contained.

Solid teal arrows show local data. Dashed navy arrows show control/state.
Dashed amber arrows show optional network requests/responses. The privacy strip
applies across capture, STT, activation and storage. The main loop handles active
tools and reminder playback. GPIO observes state and supplies software permission.
The Pi5 is a target: physical GPIO, ARM64 inference and boot behavior remain unverified.
The pipeline is sequential and half-duplex, with optional experimental stop monitoring.

Read ../hackathon-presentation/repository-evaluation.md for full flow, evidence,
configuration defaults, qualifications and privacy limitations.
