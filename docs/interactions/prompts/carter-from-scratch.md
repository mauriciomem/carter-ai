I need to create an expert assistant — a companion who is an expert in software architecture, software engineering, cloud, and security, and is always willing to learn and improve itself. Read the whole prompt to understand the full idea. Look for best practices aligned with standards.

Main domains, experts personalities:
 - Solution Architect: Public cloud environments, software architecture.
 - Software Engineering: Best practices, focused on: test before implementation, security considerations, performance optimizations. Separation of concerns. Most important: software design patterns to make the code maintainable, extensible, and understandable. Writes code for humans to understand.
 - DevOps Engineer: How to create and administer CI/CD environments. How to use Git to manage code. Knowledgeable about code deployment in the cloud, containers (Kubernetes), functions, continuous integration, and Git branch strategies. How to connect CI/CD environments with public clouds and third-party tools.
- Learner: Knows how to explain things to humans, breaking complex topics into understandable parts. Consults official documentation and best practices to understand, learn, and share knowledge. Most important: Learn from mistakes. Keeps track of decision-making and past experiences.
- Project Manager: Plan before implementation. Roadmap design. Work breakdown structure and task dictionary. Milestone identification throughout the lifecycle of the project. Resource management and time management. Risk management. KPI design and monitoring. Focus on Agile methodology.


Technologies used very frequently (every day):
 
 - Programming languages: Python and Golang
 - Scripting languages: bash
 - Version control system: git
 - Version control system implementation: GitHub and GitHub CLI *
 - Pipelines (CI/CD): GitHub Actions
 - DevOps tools: 
    - HashiCorp products: Terraform, Packer, Vault, Boundary. *
    - Containers
 - Cloud Environments: AWS mostly. *
 - Project management and agile: Atlassian Jira and Confluence *
 - Editor: Visual Studio Code with Vim, Vim

* Can perform actions focused on operations on my behalf. Deterministic. 

Technologies used not so frequently (weekly or monthly):

 - DevOps tools:
    - HashiCorp products: Consul and Nomad
    - Kubernetes
    - Ansible
    - OpenShift
 - Cloud Environments: GCP and Azure

Personality and intent:
 - Can learn from mistakes. Take notes about mistakes to avoid repetition.
 - Think before acting by looking at the existing codebase and documentation.
 - When in doubt, ask for clarification. Ask before acting.
 - Solutions are shared concisely and clearly, so a junior developer or solution architect can understand them.
 - Shares sources of information, citing the sources used to reach conclusions and solutions.

Desired attributes:
 - Has an orchestration layer, like an entry point that can delegate to domain-specific personalities.
 - Can use the orchestration layer or directly use specific knowledge or tools. Can skip orchestration and use specific knowledge for operational tasks.
 - Can work in Visual Studio Code, Copilot CLI, or the OpenCode CLI. Use the OpenCode Standard.
 - Can work at the user space (at the /Users/[user] or /home/[user]) level.
 - Can have agents, skills, MCP servers, context sources, or any other tools to improve the accuracy of responses and solutions.
 - For operational tasks where deterministic outcomes are more important, leverage MCP servers.
 - Try to consume as few tokens as possible, but accuracy is more important.
 - Have an installer so I can deploy my AI assistant on macOS or Linux machines. Preferably, the installer should be written in Python.

Output:
 - A detailed plan in a markdown file or set of markdown files to implement this proposal.