import pickle
import random
import torch
import torch.autograd as autograd
import torch.utils.data as data
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

class AnswerSelection(nn.Module):
    def __init__(self, conf):
        super(AnswerSelection, self).__init__()
        self.vocab_size = conf['vocab_size']
        self.hidden_dim = conf['hidden_dim']
        self.embedding_dim = conf['embedding_dim']
        self.question_len = conf['question_len']
        self.answer_len = conf['answer_len']

        self.word_embeddings = nn.Embedding(self.vocab_size, self.embedding_dim)
        self.lstm = nn.LSTM(self.embedding_dim, self.hidden_dim / 2, num_layers=1, bidirectional=True)
        self.cnns = [nn.Conv1d(256, 500, filter_size, stride=1, padding=filter_size-(i+1)) for i, filter_size in enumerate([1,3,5])]
        self.question_maxpool = nn.MaxPool1d(self.question_len, stride=1)
        self.answer_maxpool = nn.MaxPool1d(self.answer_len, stride=1)
        self.dropout = nn.Dropout(p=0.2)

    def forward(self, question, answer):
        question_embedding = self.word_embeddings(question)
        answer_embedding = self.word_embeddings(answer)

        q_lstm,_ = self.lstm(question_embedding)
        a_lstm,_ = self.lstm(answer_embedding)

        q_lstm = q_lstm.view(-1,self.hidden_dim, self.question_len)
        a_lstm = a_lstm.view(-1,self.hidden_dim, self.answer_len)

        question_pool = []
        answer_pool = []
        for cnn in self.cnns:
            question_conv = cnn(q_lstm)
            answer_conv = cnn(a_lstm)
            question_max_pool = self.question_maxpool(question_conv)
            answer_max_pool = self.answer_maxpool(answer_conv)
            question_activation = F.tanh(torch.squeeze(question_max_pool))
            answer_activation = F.tanh(torch.squeeze(answer_max_pool))
            question_pool.append(question_activation)
            answer_pool.append(answer_activation)

        question_output = torch.cat(question_pool, dim=1)
        answer_output = torch.cat(answer_pool, dim=1)

        question_output = self.dropout(question_output)
        answer_output = self.dropout(answer_output)

        similarity = F.cosine_similarity(question_output, answer_output, dim=1)

        return similarity

    def fit(self, questions, good_answers, bad_answers):

        good_similarity = self.forward(questions, good_answers)
        bad_similarity = self.forward(questions, bad_answers)

        similarity = torch.stack([good_similarity,bad_similarity],dim=1)
        loss = torch.stack(map(lambda x: F.relu(0.05 - x[0] + x[1]),similarity), dim=0)
        return torch.squeeze(loss).sum()

class Evaluate():
    def __init__(self, conf):
        self.conf = conf
        self.answers = self.load('answers')
        self.vocab = self.load('vocabulary')
        self.conf['vocab_size'] = len(self.vocab) + 1
        self.model = AnswerSelection(self.conf)

    def load(self, name):
        return pickle.load(open('insurance_qa_python/'+name))

    def pad_question(self, data):
        return self.pad(data, self.conf.get('question_len', None))

    def pad_answer(self, data):
        return self.pad(data, self.conf.get('answer_len', None))

    def id_to_word(self, sentence):
        return [self.vocab.get(i,'<PAD>') for i in sentence]

    def pad(self, data, max_length):
        for i, item in enumerate(data):
            if len(item) >= max_length:
                data[i] = item[:max_length]
            elif len(item) < max_length:
                data[i] += [0] * (max_length - len(item))
        return data

    def train(self):
        batch_size = self.conf['batch_size']
        epochs = self.conf['epochs']
        training_set = self.load('train')

        total_loss = 0.0

        questions = list()
        good_answers = list()
        indices = list()
        for i, q in enumerate(training_set):
            questions += [q['question']] * len(q['answers'])
            good_answers += [self.answers[j] for j in q['answers']]
            indices += [i] * len(q['answers'])

        questions = torch.LongTensor(self.pad_question(questions))
        good_answers = torch.LongTensor(self.pad_answer(good_answers))
        optimizer = torch.optim.Adam(self.model.parameters(), lr=self.conf['learning_rate'])

        for i in xrange(epochs):
            bad_answers = torch.LongTensor(self.pad_answer(random.sample(self.answers.values(), len(good_answers))))
            train_loader = data.DataLoader(dataset=torch.cat([questions,good_answers,bad_answers],dim=1), batch_size=batch_size)
            for step, train in enumerate(train_loader):
                batch_question = autograd.Variable(train[:,:self.conf['question_len']])
                batch_good_answer = autograd.Variable(train[:,self.conf['question_len']:self.conf['question_len']+self.conf['answer_len']])
                batch_bad_answer = autograd.Variable(train[:,self.conf['question_len']+self.conf['answer_len']:])

                loss = self.model.fit(batch_question, batch_good_answer, batch_bad_answer)
                print "Epoch: {0} Step: {1} out of {2} -- Current loss: {3}".format(str(i), str(step), str(len(train_loader)), str(loss.data[0]))
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
            torch.save(self.model, "saved_model/answer_selection_model")

conf = {
    'question_len':20,
    'answer_len':150,
    'batch_size':100,
    'epochs':10,
    'embedding_dim':256,
    'hidden_dim':256,
    'learning_rate':0.001,
    'margin':0.05
}
ev = Evaluate(conf)
ev.train()
