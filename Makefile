# Configuration variables
IMAGE_NAME := graphrag
IMAGE_NAMESPACE := ai
IMAGE_VERSION := $(shell sed -n 's/^version *= *"\(.*\)"/\1/p' pyproject.toml)
DOCKER_BUILDER_NAME := ${IMAGE_NAME}-demo
DOCKERFILE := demos/Dockerfile
BUILD_CONTEXT := .

# Registries (override via env / make VAR=...). Default to the two Stratus5 registries.
PRODUCTION_CA_REGISTRY ?= dreg-ca.stratus5.net
PRODUCTION_EU_REGISTRY ?= dreg-eu.stratus5.net

DOCKER_BUILD := docker buildx build --builder ${DOCKER_BUILDER_NAME} --load --pull
TRIVY_TIMEOUT := 30m0s

# trivy runs inside a podman toolbox (a shim at ~/.local/bin/trivy) and cannot reach
# the host docker socket. So `verify` never scans the local daemon by image name; it
# exports the freshly built image to a tarball on shared $HOME and scans it with --input.
SCAN_TAR := ${CURDIR}/.trivy-image.tar

# Image tags
IMAGE_TAGS := ${IMAGE_VERSION} latest

# Build Args (demos/Dockerfile takes none today; add here as needed)
BUILD_ARGS :=

# Helper function to convert string to uppercase
UC = $(shell echo '$1' | tr '[:lower:]' '[:upper:]')

# Generate image names -> dreg-ca.stratus5.net/ai/graphrag , dreg-eu.stratus5.net/ai/graphrag
DOCKER_CA_IMAGE := ${PRODUCTION_CA_REGISTRY}/${IMAGE_NAMESPACE}/${IMAGE_NAME}
DOCKER_EU_IMAGE := ${PRODUCTION_EU_REGISTRY}/${IMAGE_NAMESPACE}/${IMAGE_NAME}
DOCKER_IMAGE := ${DOCKER_CA_IMAGE} ${DOCKER_EU_IMAGE}

# Phony targets
.PHONY: help build verify verifySrc publish clean publish_ca_registry publish_eu_registry create_builder prune_builder_cache delete_builder builder_diskusage

# Show available targets
help:
	@echo ""; \
	echo "GraphRAG demo image build — ${DOCKER_CA_IMAGE}:${IMAGE_VERSION}"; \
	echo "                            ${DOCKER_EU_IMAGE}:${IMAGE_VERSION}"; \
	echo "------------------------------------------------------------------------"; \
	echo "  build                 Build the demo image (all tags, both registries)"; \
	echo "  verify                Trivy vuln scan of the built image"; \
	echo "  verifySrc             Trivy vuln scan of the project source tree"; \
	echo "  publish               Push all tags to both registries"; \
	echo "  publish_ca_registry   Push all tags to ${PRODUCTION_CA_REGISTRY}"; \
	echo "  publish_eu_registry   Push all tags to ${PRODUCTION_EU_REGISTRY}"; \
	echo "  clean                 Remove local images + tear down the buildx builder"; \
	echo "  create_builder        Create the buildx builder if missing"; \
	echo "  prune_builder_cache   Prune the buildx builder cache"; \
	echo "  delete_builder        Remove the buildx builder"; \
	echo "  builder_diskusage     Show buildx builder disk usage"; \
	echo ""

# Build docker images
build: create_builder
	@echo ""; \
	echo "BUILDING $(call UC,${IMAGE_NAME}:${IMAGE_VERSION}) DEMO IMAGE"; \
	echo "------------------------------------------------------------------------"; \
	tags=""; \
	for image in ${DOCKER_IMAGE}; do \
		for image_tag in $(IMAGE_TAGS); do \
			tags="$$tags --tag $$image:$$image_tag"; \
		done; \
	done; \
	buildArgs=""; \
	for build_arg in $(BUILD_ARGS); do \
		buildArgs="$$buildArgs --build-arg $$build_arg"; \
	done; \
	${DOCKER_BUILD} -f ${DOCKERFILE} $$buildArgs $$tags ${BUILD_CONTEXT}

# Verify docker images
# Exports the local image to a tarball first, then scans with --input, so it works
# whether trivy runs natively or inside a toolbox with no access to the docker daemon.
verify:
	@echo ""; \
	echo "VERIFYING $(call UC,${IMAGE_NAME}:${IMAGE_VERSION}) DEMO IMAGE"; \
	echo "-------------------------------------------------------------------------"; \
	trap 'rm -f "${SCAN_TAR}"' EXIT; \
	echo "Exporting ${DOCKER_CA_IMAGE}:${IMAGE_VERSION} -> ${SCAN_TAR} for daemon-free scan"; \
	docker save ${DOCKER_CA_IMAGE}:${IMAGE_VERSION} -o "${SCAN_TAR}"; \
	if curl -s --connect-timeout 3 http://localhost:4954/healthz >/dev/null 2>&1; then \
		echo "Using local Trivy server at localhost:4954"; \
		trivy image \
			--server http://localhost:4954 \
			--scanners vuln \
			--ignore-unfixed \
			--exit-code 0 \
			--severity CRITICAL,HIGH \
			--timeout ${TRIVY_TIMEOUT} \
			--input "${SCAN_TAR}"; \
	else \
		echo "Trivy server not available, falling back to container-based scanning"; \
		docker run --rm \
			-v /tmp/trivy-cache/${DOCKER_BUILDER_NAME}/:/root/.cache/ \
			-v "${SCAN_TAR}:/scan/image.tar:ro" \
			-e "TRIVY_DB_REPOSITORY=public.ecr.aws/aquasecurity/trivy-db" \
			-e "TRIVY_JAVA_DB_REPOSITORY=public.ecr.aws/aquasecurity/trivy-java-db" \
			aquasec/trivy \
			image --scanners vuln --ignore-unfixed --exit-code 0 --severity CRITICAL,HIGH --timeout ${TRIVY_TIMEOUT} \
			--input /scan/image.tar; \
	fi

# Verify source files
verifySrc:
	@echo ""; \
	echo "VERIFYING $(call UC,${IMAGE_NAME}) PROJECT FOR VULNERABILITIES"; \
	echo "--------------------------------------------------------------"; \
	if curl -s --connect-timeout 3 http://localhost:4954/healthz >/dev/null 2>&1; then \
		echo "Using local Trivy server at localhost:4954"; \
		trivy fs \
			--server http://localhost:4954 \
			--scanners vuln \
			--ignore-unfixed \
			--exit-code 1 \
			--severity CRITICAL,HIGH \
			--timeout ${TRIVY_TIMEOUT} \
			.; \
	else \
		echo "Trivy server not available, falling back to container-based scanning"; \
		docker run --rm \
			-v /tmp/trivy-cache/${DOCKER_BUILDER_NAME}/:/root/.cache/ \
			-v "${PWD}:/usr/src/" \
			-e "TRIVY_DB_REPOSITORY=public.ecr.aws/aquasecurity/trivy-db" \
			-e "TRIVY_JAVA_DB_REPOSITORY=public.ecr.aws/aquasecurity/trivy-java-db" \
			aquasec/trivy fs --exit-code 1 --scanners vuln --severity CRITICAL,HIGH --timeout ${TRIVY_TIMEOUT} /usr/src/; \
	fi

# Publish images to docker registries
publish:
	@echo ""; \
	echo "PUBLISHING $(call UC,${IMAGE_NAME}:${IMAGE_VERSION}) DEMO IMAGE TO REGISTRIES"; \
	echo "----------------------------------------------------------------------------------------"; \
	for image in ${DOCKER_IMAGE}; do \
		for image_tag in $(IMAGE_TAGS); do \
			docker push $$image:$$image_tag; \
		done; \
	done

# Prune the builder and remove built images
clean: prune_builder_cache delete_builder
	@echo ""; \
	echo "REMOVING BUILT $(call UC,${IMAGE_NAME}:${IMAGE_VERSION}) DEMO IMAGE FROM BUILD SERVER"; \
	echo "----------------------------------------------------------------------------------------------------"; \
	rm -f "${SCAN_TAR}"; \
	for image in $(DOCKER_IMAGE); do \
		for image_tag in $(IMAGE_TAGS); do \
			docker rmi --force $$image:$$image_tag; \
		done; \
	done

# Publish to CA registry
publish_ca_registry:
	@echo ""; \
	echo "PUBLISHING ALL IMAGES TO CA REGISTRY"; \
	echo "------------------------------------"; \
	for image_tag in $(IMAGE_TAGS); do \
		docker push ${DOCKER_CA_IMAGE}:$$image_tag; \
	done

# Publish to EU registry
publish_eu_registry:
	@echo ""; \
	echo "PUBLISHING ALL IMAGES TO EU REGISTRY"; \
	echo "------------------------------------"; \
	for image_tag in $(IMAGE_TAGS); do \
		docker push ${DOCKER_EU_IMAGE}:$$image_tag; \
	done

# Builder-related commands
create_builder:
	@if ! docker buildx inspect ${DOCKER_BUILDER_NAME} > /dev/null 2>&1; then \
		docker buildx create --name ${DOCKER_BUILDER_NAME}; \
	fi

prune_builder_cache:
	@docker buildx --builder ${DOCKER_BUILDER_NAME} prune -af || true

delete_builder: prune_builder_cache
	@if docker buildx inspect ${DOCKER_BUILDER_NAME} > /dev/null 2>&1; then \
		docker buildx rm ${DOCKER_BUILDER_NAME} -f; \
	fi

builder_diskusage:
	@if docker buildx inspect ${DOCKER_BUILDER_NAME} > /dev/null 2>&1; then \
		docker buildx --builder ${DOCKER_BUILDER_NAME} du; \
	fi
