The train.py script is our automated fine-tuning pipeline. When executed, it performs the following steps end-to-end:
1. Data Ingestion: It connects to our SQLite database (weather_reports_balanced.db) and extracts the dataset prepared by the team—specifically the text_clean (the report text) and ml_label (1 for Fake, 0 for Real) columns.
2. Preprocessing: It splits the data (80% for training, 20% for testing) and tokenizes the text, converting human-readable words into numerical IDs that the neural network can process.
3. Model Fine-Tuning: It downloads a foundational language model (distilbert-base-uncased), replaces its default predictive head with a custom binary classification head, and trains it for 3 epochs to recognize patterns specific to fake weather reports.
4. Export: Once the model reaches its highest accuracy, the script saves the finalized weights to the local file system.

After train.py successfully finishes, it generates the models/saved_model/ directory. This is our production-ready artifact folder.
It contains:
1. model.safetensors: The actual trained neural network weights (~250MB).
2. config.json: The architectural rules for the model.
3. tokenizer.json & vocab.txt: The vocabulary dictionary needed to format incoming live data exactly like our training data.