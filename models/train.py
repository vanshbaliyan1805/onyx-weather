import sqlite3
import pandas as pd
import torch
from datasets import Dataset
from transformers import AutoTokenizer, AutoModelForSequenceClassification, TrainingArguments, Trainer
from sklearn.model_selection import train_test_split

# 1. Load Data from SQLite
# Target the database located just outside the current code directory
db_path = '/Users/vanshbaliyan/onyx/onyx-weather/models/weather_reports_balanced.db'
conn = sqlite3.connect(db_path)
df = pd.read_sql_query("SELECT text_clean, ml_label FROM weather_reports", conn)
conn.close()

# Clean data and ensure labels are integers (assuming 1 = Fake, 0 = Real)
df = df.dropna(subset=['text_clean', 'ml_label'])
df['ml_label'] = df['ml_label'].astype(int)

# 2. Prepare Train/Validation Splits
train_df, val_df = train_test_split(df, test_size=0.2, random_state=42)
train_dataset = Dataset.from_pandas(train_df)
val_dataset = Dataset.from_pandas(val_df)

# 3. Tokenization using DistilBERT uncased
model_id = "distilbert-base-uncased"
tokenizer = AutoTokenizer.from_pretrained(model_id)

def tokenize_function(examples):
    return tokenizer(
        examples["text_clean"], 
        padding="max_length", 
        truncation=True, 
        max_length=128
    )

train_tokenized = train_dataset.map(tokenize_function, batched=True)
val_tokenized = val_dataset.map(tokenize_function, batched=True)

# Hugging Face Trainer expects the label column to be named strictly "labels"
train_tokenized = train_tokenized.rename_column("ml_label", "labels")
val_tokenized = val_tokenized.rename_column("ml_label", "labels")

# Keep only the features required by the PyTorch model
columns_to_keep = ["input_ids", "attention_mask", "labels"]
train_tokenized.set_format("torch", columns=columns_to_keep)
val_tokenized.set_format("torch", columns=columns_to_keep)

# 4. Initialize Model
# num_labels=2 for binary classification
model = AutoModelForSequenceClassification.from_pretrained(model_id, num_labels=2)

# 5. Define Training Arguments and Trainer
training_args = TrainingArguments(
    output_dir="./distilbert_fake_weather_model",
    eval_strategy="epoch",
    save_strategy="epoch",
    learning_rate=2e-5,
    per_device_train_batch_size=16,
    per_device_eval_batch_size=16,
    num_train_epochs=3,
    weight_decay=0.01,
    load_best_model_at_end=True,
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_tokenized,
    eval_dataset=val_tokenized,
    processing_class=tokenizer,
)

# 6. Execute Fine-Tuning and Save
print("Starting fine-tuning...")
trainer.train()

# Save the final artifacts to a dedicated directory for the API to load
trainer.save_model("./saved_model")
tokenizer.save_pretrained("./saved_model")
print("Model saved to ./saved_model")