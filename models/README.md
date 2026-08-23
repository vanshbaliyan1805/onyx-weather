1. Fake & Misleading Report Detection
Detecting fake weather claims or sensationalized posts (e.g., exaggerated flood warnings) requires intent analysis and trust scoring.
Primary Choice: Fine-Tuned IndicBERT or RoBERTa
    Why: Weather reports from India frequently feature code-mixing (Hinglish/Kanglish) or localized names. IndicBERT handles multilingual and transliterated inputs effectively.
    Approach: Frame it as binary classification (0: Trustworthy/Informational, 1: Clickbait/Sensational/Fake).
Lightweight Baseline: TF-IDF + XGBoost
    Why: Fast to train and run as a sanity check. Extracts clickbait indicators (e.g., ALL CAPS, extreme punctuation like "!!!", sensational keywords).

2. Duplicate & Near-Duplicate Removal
Social media naturally amplifies duplicates via retweets, copy-pasted posts, and news bots. Exact text matching will miss slightly rephrased duplicates.
Primary Choice: Sentence-BERT (SBERT) + Cosine Similarity
    Why: Generates dense semantic vector embeddings for each post.
    Approach: Pass incoming posts through all-MiniLM-L6-v2 or paraphrase-multilingual-MiniLM-L12-v2. Compute cosine similarity against posts from the same region/time window (e.g., last 2 hours). If similarity score is > 0.85, flag as duplicate.
Scale Optimization: MinHash LSH (Locality-Sensitive Hashing) or FAISS
    Why: Comparing every new post to thousands of existing posts directly is computationally expensive (O(N^2)). Vector search libraries like FAISS or LSH retrieve exact vector neighbors in milliseconds at Big Data scale.

3. Automatic Event Categorization
Categorize posts into target classes: Rainfall, Thunderstorms, Floods, Heatwaves, Fog, Dust Storms, Strong Winds, or Neutral/Irrelevant.
Primary Choice: Zero-Shot Classification (BART-Large-MNLI or DeBERTa-v3)
    Why: Extremely fast implementation—requires no labeled training data initially. You provide candidates directly as text strings (["rain", "flooding", "thunderstorm", "heatwave"]), and the model computes label probability.
Production Option: Fine-Tuned DistilBERT / IndicBERT Multi-Label Classifier
    Why: Once you label a small dataset (~500–1000 posts), fine-tune a compact BERT variant.
    Multi-Label Setup: Use Sigmoid outputs instead of Softmax, allowing a post like "Heavy rain causing severe urban flooding in MG Road" to be tagged with both Rainfall and Floods.


Recommended Tech Stack & Pipeline

Pipeline Stage              Recommended Tool / Framework
Embeddings & NLP            Hugging Face Transformers, Sentence-Transformers
Vector Search Indexing      FAISS or ChromaDB
Traditional ML Baseline     Scikit-Learn, XGBoost
Data Ingestion Buffer       Pandas / Polars (for batch processing DB feeds)


Execution Strategy

Phase 1 (Day 1 - Quick Prototyping): Build baseline models using TF-IDF + Logistic Regression/XGBoost for multi-label text categorization, paired with exact string hashing (MD5) for duplicate checking.
Phase 2 (Deep Learning Core): Switch to Sentence-BERT embeddings. Store embeddings in FAISS for rapid semantic deduplication.
Phase 3 (Hackathon Pitch Readiness): Fine-tune IndicBERT for high accuracy on Indian weather context and integrate confidence scores (0.0 - 1.0) for your teammate's Admin Dashboard filters.