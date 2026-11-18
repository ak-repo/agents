.DEFAULT_GOAL := help
.PHONY: help list new

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-6s %s\n", $$1, $$2}'
	@echo
	@echo "Run an agent's own targets with: make -C <agent> <target>   e.g. make -C expense-agent web"

list: ## List the agents in this repo
	@for d in */; do d=$${d%/}; \
		case $$d in _*) continue;; esac; \
		[ -f "$$d/README.md" ] || continue; \
		printf '  %-20s %s\n' "$$d" "$$(awk 'NF && !/^#/ {print; exit}' "$$d/README.md" | tr -d '*' | cut -c1-90)"; \
	done

new: ## Create an agent from the template: make new NAME=my-agent
	@test -n "$(NAME)" || { echo "usage: make new NAME=my-agent"; exit 1; }
	@case "$(NAME)" in *[!a-z0-9-]*|-*|_*) echo "NAME must be lowercase letters, digits and dashes"; exit 1;; esac
	@test ! -e "$(NAME)" || { echo "$(NAME) already exists"; exit 1; }
	cp -r _template "$(NAME)"
	sed -i 's/{{NAME}}/$(NAME)/g' "$(NAME)/README.md"
	@echo "Created $(NAME)/. Next: edit $(NAME)/README.md, add a row to the table in the root README.md."
