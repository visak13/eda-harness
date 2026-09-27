# Reference

Every page in this section is **generated when the site is built**, from the same declarations the product runs
on, so it always matches the version you are reading (**{{ heronry.version }}**).

| Page | Generated from |
|---|---|
| [Command line](cli.md) | the command table `{{ brand.cli_name }} help` prints |
| [Settings](settings.md) | the settings registry: every environment variable, `config.toml` key, default and tier |
| [REST API](rest-api.md) | the board's OpenAPI document ([openapi.json](openapi.json)) |
| [MCP tools](mcp-tools.md) | the tool definitions every seat's MCP server advertises |
| [Workflow schema](workflow-schema.md) | the workflow definition model ([workflow.schema.json](workflow.schema.json)) |
| [Models catalog](models.md) | the models catalog's field table |

Found a gap? The reference cannot be edited by hand: fix the declaration in the product, and the next build
carries it.
