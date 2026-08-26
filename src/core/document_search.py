from config import settings, PROJECT_ROOT
import os, logging

logger = logging.getLogger("token")
CHROMA_PATH = os.path.join(PROJECT_ROOT, "storage", "chroma_db")

_embeddings = None
_splitter = None
_vectorstore = None
_reranker = None

def _get_vectorstore():
    global _embeddings, _splitter, _vectorstore, _reranker
    
    if _vectorstore is None:
        
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_chroma import Chroma
        from langchain_community.cross_encoders import HuggingFaceCrossEncoder
        from langchain_classic.retrievers.document_compressors.cross_encoder_rerank import CrossEncoderReranker
        
        
        _embeddings = HuggingFaceEmbeddings(model_name=settings.embedder)
        _splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=200)
        _vectorstore = Chroma(collection_name="document", embedding_function=_embeddings, persist_directory=CHROMA_PATH)
        _reranker_model = HuggingFaceCrossEncoder(model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")
        _reranker = CrossEncoderReranker(model=_reranker_model, top_n=3)
    return _vectorstore


def list_index_doc():
    try:
        result = _get_vectorstore().get(include=['metadatas'])
        seen = {}
        for meta in result['metadatas']:
            doc_id = meta.get("doc_id")
            source = meta.get("source", "unknown")
            if doc_id and doc_id not in seen:
                seen[doc_id] = source
        return seen
    except Exception as e:
        logger.error(f"[LIST_DOC] empty : {e}")
        return {}

def index_doc(file_path, doc_id):
    from langchain_community.document_loaders import PyMuPDFLoader
    from langchain_core.documents import Document
    
    file_path = os.path.expanduser(file_path)
    if not file_path or not file_path.strip():
        raise ValueError("file_path cannot be empty")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    if os.path.getsize(file_path) == 0:
        raise ValueError(f"File is empty: {file_path}")
    if not doc_id or not doc_id.strip():
        raise ValueError("doc_id cannot be empty")
    
    vs = _get_vectorstore()
    loader = PyMuPDFLoader(file_path)
    pages = loader.load()
    full_chunks = []
    chunk_index = 0
    
    for page in pages:
        page_number = page.metadata.get("page", 0) + 1
        chunks = _splitter.split_text(page.page_content)
        for chunk in chunks:
            full_chunks.append(
                Document(page_content=chunk,
                    metadata={"doc_id": doc_id, "chunk_index": chunk_index,
                              "page": page_number, "source": file_path}))
            chunk_index += 1
    ids = [f"{doc_id}_{i}" for i in range(len(full_chunks))]
    try:
        existing = vs.get(where={"doc_id": doc_id})
        if existing["ids"]:
            vs.delete(ids=existing["ids"])
            logger.info(f"[INDEX] removed {len(existing['ids'])} old chunks - {doc_id}")
    except Exception as e:
        logger.warning(f"[INDEX] could not clean old chunks for {doc_id}: {e}")
    vs.add_documents(full_chunks, ids=ids)
    return len(full_chunks)

def search_doc(query, doc_id, top_k=3, rerank=10):
    from langchain_classic.retrievers import ContextualCompressionRetriever
    
    vs = _get_vectorstore()
    search_kwargs = {'k': rerank}
    if doc_id:
        search_kwargs['filter'] = {'doc_id': doc_id}
    base_retriever = vs.as_retriever(search_kwargs=search_kwargs)
    compress_retriever = ContextualCompressionRetriever(
        base_compressor=_reranker,
        base_retriever=base_retriever
    )
    results = compress_retriever.invoke(query)
    return [
        {"text": doc.page_content, "chunk_index": doc.metadata.get("chunk_index"), "page": doc.metadata.get("page")}
        for doc in results[:top_k]
    ]

def search_all_doc(query, top_k=3, rerank=10):
    from langchain_classic.retrievers import ContextualCompressionRetriever
    
    
    vs = _get_vectorstore()
    base_retriever = vs.as_retriever(search_kwargs={'k': rerank})
    compress_retriever = ContextualCompressionRetriever(
        base_compressor=_reranker,
        base_retriever=base_retriever
    )
    results = compress_retriever.invoke(query)
    return [
        {'text': doc.page_content, 'doc_id': doc.metadata.get("doc_id"),
         'page': doc.metadata.get("page"), 'source': doc.metadata.get("source")}
        for doc in results[:top_k]
    ]

def index_folder(folder_path):
    results = {}
    if not os.path.isdir(folder_path):
        raise ValueError(f"Not a directory: {folder_path}")
    pdf_files = [f for f in os.listdir(folder_path) if f.lower().endswith(".pdf")]
    if not pdf_files:
        return {}
    for filename in pdf_files:
        file_path = os.path.join(folder_path, filename)
        doc_id = os.path.splitext(filename)[0]
        try:
            chunks = index_doc(file_path, doc_id)
            results[doc_id] = chunks
            logger.info(f"Indexed {doc_id} | {chunks} chunks")
        except Exception as e:
            logger.error(f"Failed to index {filename}: {e}")
            results[doc_id] = 0
    return results