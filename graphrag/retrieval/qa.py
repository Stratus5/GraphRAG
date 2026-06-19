from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You answer strictly from the provided context. "
     "Cite source files in parentheses. If the answer is not in the "
     "context, say you don't know."),
    ("human", "Question: {question}\n\nContext:\n{context}"),
])


def build_context(chunks: list[dict], facts: list[dict]) -> str:
    lines = ["## Passages"]
    for c in chunks:
        lines.append(f"[{c['source']}] {c['text']}")
    if facts:
        lines.append("\n## Known facts")
        for f in facts:
            lines.append(f"- {f['subject']} {f['predicate']} {f['object']}")
    return "\n".join(lines)


def answer(llm: BaseChatModel, question: str, chunks: list[dict], facts: list[dict]) -> str:
    context = build_context(chunks, facts)
    chain = PROMPT | llm
    return chain.invoke({"question": question, "context": context}).content
