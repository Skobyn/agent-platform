"""In-memory data store with optional Firestore backend.

When Firestore is available, data is persisted there.
When not, everything runs in-memory (fully functional, but data resets on container restart).
"""
import os
import uuid
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, List

# Try Firestore
_firestore_client = None
_firestore_checked = False
GCP_PROJECT = os.environ.get("GCP_PROJECT", "apex-internal-apps")

def _get_firestore():
    global _firestore_client, _firestore_checked
    if _firestore_checked:
        return _firestore_client
    _firestore_checked = True
    try:
        from google.cloud import firestore
        client = firestore.Client(project=GCP_PROJECT)
        # Test connection
        list(client.collection("_ping").limit(1).stream())
        _firestore_client = client
        print(f"[store] Firestore connected: {GCP_PROJECT}")
    except Exception as e:
        print(f"[store] Firestore unavailable ({e}), using in-memory store")
        _firestore_client = None
    return _firestore_client


class InMemoryCollection:
    """Thread-safe in-memory document collection."""
    
    def __init__(self):
        self._data: Dict[str, dict] = {}
        self._lock = threading.Lock()
    
    def get(self, doc_id: str) -> Optional[dict]:
        with self._lock:
            doc = self._data.get(doc_id)
            return dict(doc) if doc else None
    
    def set(self, doc_id: str, data: dict):
        with self._lock:
            self._data[doc_id] = dict(data)
    
    def update(self, doc_id: str, data: dict):
        with self._lock:
            if doc_id in self._data:
                self._data[doc_id].update(data)
    
    def delete(self, doc_id: str):
        with self._lock:
            self._data.pop(doc_id, None)
    
    def query(self, field: str, value) -> List[dict]:
        with self._lock:
            results = []
            for doc_id, doc in self._data.items():
                if doc.get(field) == value:
                    d = dict(doc)
                    d["id"] = doc_id
                    results.append(d)
            return results
    
    def all(self) -> List[dict]:
        with self._lock:
            results = []
            for doc_id, doc in self._data.items():
                d = dict(doc)
                d["id"] = doc_id
                results.append(d)
            return results


class Store:
    """Unified store with Firestore fallback to in-memory."""
    
    def __init__(self):
        self._memory: Dict[str, InMemoryCollection] = {}
        self._lock = threading.Lock()
    
    def _get_collection(self, name: str) -> InMemoryCollection:
        with self._lock:
            if name not in self._memory:
                self._memory[name] = InMemoryCollection()
            return self._memory[name]
    
    @property
    def _fs(self):
        return _get_firestore()
    
    # --- Document operations ---
    
    def get_doc(self, collection: str, doc_id: str) -> Optional[dict]:
        fs = self._fs
        if fs:
            try:
                doc = fs.collection(collection).document(doc_id).get()
                if doc.exists:
                    data = doc.to_dict()
                    data["id"] = doc.id
                    return data
                return None
            except Exception as e:
                print(f"[store] Firestore get error: {e}")
        doc = self._get_collection(collection).get(doc_id)
        if doc:
            doc["id"] = doc_id
        return doc
    
    def set_doc(self, collection: str, doc_id: str, data: dict):
        fs = self._fs
        if fs:
            try:
                clean = {k: v for k, v in data.items() if k != "id"}
                fs.collection(collection).document(doc_id).set(clean)
                return
            except Exception as e:
                print(f"[store] Firestore set error: {e}")
        self._get_collection(collection).set(doc_id, data)
    
    def update_doc(self, collection: str, doc_id: str, data: dict):
        fs = self._fs
        if fs:
            try:
                clean = {k: v for k, v in data.items() if k != "id"}
                fs.collection(collection).document(doc_id).update(clean)
                return
            except Exception as e:
                print(f"[store] Firestore update error: {e}")
        self._get_collection(collection).update(doc_id, data)
    
    def delete_doc(self, collection: str, doc_id: str):
        fs = self._fs
        if fs:
            try:
                fs.collection(collection).document(doc_id).delete()
                return
            except Exception as e:
                print(f"[store] Firestore delete error: {e}")
        self._get_collection(collection).delete(doc_id)
    
    def query_docs(self, collection: str, field: str, value) -> List[dict]:
        fs = self._fs
        if fs:
            try:
                docs = fs.collection(collection).where(field, "==", value).stream()
                results = []
                for doc in docs:
                    data = doc.to_dict()
                    data["id"] = doc.id
                    results.append(data)
                return results
            except Exception as e:
                print(f"[store] Firestore query error: {e}")
        return self._get_collection(collection).query(field, value)
    
    def list_docs(self, collection: str) -> List[dict]:
        fs = self._fs
        if fs:
            try:
                docs = fs.collection(collection).stream()
                results = []
                for doc in docs:
                    data = doc.to_dict()
                    data["id"] = doc.id
                    results.append(data)
                return results
            except Exception as e:
                print(f"[store] Firestore list error: {e}")
        return self._get_collection(collection).all()


# Singleton
store = Store()
