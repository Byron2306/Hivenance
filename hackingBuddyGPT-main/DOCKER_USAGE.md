# Build the Docker image
# (Run this in the project root directory)
docker build -t hackingbuddygpt .

# Run the app in a container (replace <args> with your desired command-line arguments)
docker run --rm -it hackingbuddygpt <args>

# Example: Run the WebTestingWithExplanation use case with OpenAI API key
docker run --rm -it hackingbuddygpt WebTestingWithExplanation --llm.api_key=YOUR_API_KEY --llm.model=gpt-4 --llm.context_size=4096

# If you want to expose the web UI (Viewer), add -p 4444:4444 and use the Viewer command:
docker run --rm -it -p 4444:4444 hackingbuddygpt Viewer
