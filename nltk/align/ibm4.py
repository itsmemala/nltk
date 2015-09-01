# -*- coding: utf-8 -*-
# Natural Language Toolkit: IBM Model 4
#
# Copyright (C) 2001-2015 NLTK Project
# Author: Tah Wei Hoon <hoon.tw@gmail.com>
# URL: <http://nltk.org/>
# For license information, see LICENSE.TXT

"""
Translation model that reorders output words based on their type and
distance from other related words in the output sentence.

IBM Model 4 improves the distortion model of Model 3, motivated by the
observation that certain words tend to be re-ordered in a predictable
way relative to one another. For example, <adjective><noun> in English
usually has its order flipped as <noun><adjective> in French.

Model 4 requires words in the source and target vocabularies to be
categorized into classes. This can be linguistically driven, like parts
of speech (adjective, nouns, prepositions, etc). Word classes can also
be obtained by statistical methods. The original IBM Model 4 uses an
information theoretic approach to group words into 50 classes for each
vocabulary.

Terminology:
Cept:
    A source word with non-zero fertility i.e. aligned to one or more
    target words.
Tablet:
    The set of target word(s) aligned to a cept.
Head of cept:
    The first word of the tablet of that cept.
Center of cept:
    The average position of the words in that cept's tablet. If the
    value is not an integer, the ceiling is taken.
    For example, for a tablet with words in positions 2, 5, 6 in the
    target sentence, the center of the corresponding cept is
    ceil((2 + 5 + 6) / 3) = 5
Displacement:
    For a head word, defined as (position of head word - position of
    previous cept's center). Can be positive or negative.
    For a non-head word, defined as (position of non-head word -
    position of previous word in the same tablet). Always positive,
    because successive words in a tablet are assumed to appear to the
    right of the previous word.

In contrast to Model 3 which reorders words in a tablet independently of
other words, Model 4 distinguishes between three cases.
(1) Words generated by NULL are distributed uniformly.
(2) For a head word t, its position is modeled by the probability
    d_head(displacement | word_class_s(s),word_class_t(t)),
    where s is the previous cept, and word_class_s and word_class_t maps
    s and t to a source and target language word class respectively.
(3) For a non-head word t, its position is modeled by the probability
    d_non_head(displacement | word_class_t(t))

The EM algorithm used in Model 4 is:
E step - In the training data, collect counts, weighted by prior
         probabilities.
         (a) count how many times a source language word is translated
             into a target language word
         (b) for a particular word class, count how many times a head
             word is located at a particular displacement from the
             previous cept's center
         (c) for a particular word class, count how many times a
             non-head word is located at a particular displacement from
             the previous target word
         (d) count how many times a source word is aligned to phi number
             of target words
         (e) count how many times NULL is aligned to a target word

M step - Estimate new probabilities based on the counts from the E step

Like Model 3, there are too many possible alignments to consider. Thus,
a hill climbing approach is used to sample good candidates.


Notations:
i: Position in the source sentence
    Valid values are 0 (for NULL), 1, 2, ..., length of source sentence
j: Position in the target sentence
    Valid values are 1, 2, ..., length of target sentence
l: Number of words in the source sentence, excluding NULL
m: Number of words in the target sentence
s: A word in the source language
t: A word in the target language
phi: Fertility, the number of target words produced by a source word
p1: Probability that a target word produced by a source word is
    accompanied by another target word that is aligned to NULL
p0: 1 - p1
dj: Displacement, Δj


References:
Philipp Koehn. 2010. Statistical Machine Translation.
Cambridge University Press, New York.

Peter E Brown, Stephen A. Della Pietra, Vincent J. Della Pietra, and
Robert L. Mercer. 1993. The Mathematics of Statistical Machine
Translation: Parameter Estimation. Computational Linguistics, 19 (2),
263-311.
"""

from __future__ import division
from collections import defaultdict
from nltk.align import AlignedSent
from nltk.align.ibm_model import IBMModel
from nltk.align.ibm3 import IBMModel3
from math import factorial
import warnings


class IBMModel4(IBMModel):
    """
    Translation model that reorders output words based on their type and
    their distance from other related words in the output sentence

    >>> align_sents = []
    >>> align_sents.append(AlignedSent(['klein', 'ist', 'das', 'Haus'], ['the', 'house', 'is', 'small']))
    >>> align_sents.append(AlignedSent(['das', 'Haus', 'ist', 'ja', 'groß'], ['the', 'house', 'is', 'big']))
    >>> align_sents.append(AlignedSent(['das', 'Haus'], ['the', 'house']))
    >>> align_sents.append(AlignedSent(['das', 'Buch'], ['the', 'book']))
    >>> align_sents.append(AlignedSent(['ein', 'Buch'], ['a', 'book']))
    >>> src_classes = {'a': 0, 'big': 1, 'book': 2, 'house': 2, 'is': 3, 'small': 1, 'the': 0 }
    >>> trg_classes = {'das': 0, 'Buch': 1, 'ein': 0, 'groß': 2, 'Haus': 1, 'ist': 3, 'ja': 4, 'klein': 2 }

    >>> ibm4 = IBMModel4(align_sents, 5, src_classes, trg_classes)

    >>> print('{0:.1f}'.format(ibm4.translation_table['Buch']['book']))
    1.0
    >>> print('{0:.1f}'.format(ibm4.translation_table['das']['book']))
    0.0
    >>> print('{0:.1f}'.format(ibm4.translation_table[None]['book']))
    0.0

    """

    def __init__(self, sentence_aligned_corpus, iterations,
                 source_word_classes, target_word_classes,
                 probability_tables = None):
        """
        Train on ``sentence_aligned_corpus`` and create a lexical
        translation model, distortion models, a fertility model, and a
        model for generating NULL-aligned words.

        Translation direction is from ``AlignedSent.mots`` to
        ``AlignedSent.words``.

        Runs a few iterations of Model 3 training to initialize
        model parameters.

        :param sentence_aligned_corpus: Sentence-aligned parallel corpus
        :type sentence_aligned_corpus: list(AlignedSent)

        :param iterations: Number of iterations to run training algorithm
        :type iterations: int

        :param source_word_classes: Lookup table that maps a source word
            to its word class, the latter represented by an integer id
        :type source_word_classes: dict[str]: int

        :param target_word_classes: Lookup table that maps a target word
            to its word class, the latter represented by an integer id
        :type target_word_classes: dict[str]: int

        :param probability_tables: Optional. Use this to pass in custom
            probability values. If not specified, probabilities will be
            set to a uniform distribution, or some other sensible value.
            If specified, all the following entries must be present:
            ``translation_table``, ``alignment_table``,
            ``fertility_table``, ``p1``, ``head_distortion_table``,
            ``non_head_distortion_table``. See ``IBMModel`` and
            ``IBMModel4`` for the type and purpose of these tables.
        :type probability_tables: dict[str]: object
        """
        super(IBMModel4, self).__init__(sentence_aligned_corpus)
        self.reset_probabilities()
        self.src_classes = source_word_classes
        self.trg_classes = target_word_classes

        if probability_tables is None:
            # Get probabilities from IBM model 3
            ibm3 = IBMModel3(sentence_aligned_corpus, iterations)
            self.translation_table = ibm3.translation_table
            self.alignment_table = ibm3.alignment_table
            self.fertility_table = ibm3.fertility_table
            self.p1 = ibm3.p1
            self.set_uniform_distortion_probabilities(sentence_aligned_corpus)
        else:
            # Set user-defined probabilities
            self.translation_table = probability_tables['translation_table']
            self.alignment_table = probability_tables['alignment_table']
            self.fertility_table = probability_tables['fertility_table']
            self.p1 = probability_tables['p1']
            self.head_distortion_table = probability_tables[
                'head_distortion_table']
            self.non_head_distortion_table = probability_tables[
                'non_head_distortion_table']

        for k in range(0, iterations):
            self.train(sentence_aligned_corpus)

    def reset_probabilities(self):
        super(IBMModel4, self).reset_probabilities()
        self.head_distortion_table = defaultdict(
            lambda: defaultdict(lambda: defaultdict(lambda: self.MIN_PROB)))
        """
        dict[int][int][int]: float. Probability(displacement of head
        word | word class of previous cept,target word class).
        Values accessed as ``distortion_table[dj][src_class][trg_class]``.
        """

        self.non_head_distortion_table = defaultdict(
            lambda: defaultdict(lambda: self.MIN_PROB))
        """
        dict[int][int]: float. Probability(displacement of non-head
        word | target word class).
        Values accessed as ``distortion_table[dj][trg_class]``.
        """

    def set_uniform_distortion_probabilities(self, sentence_aligned_corpus):
        """
        Set distortion probabilities uniformly to
        1 / cardinality of displacement values
        """
        max_m = self.longest_target_sentence_length(sentence_aligned_corpus)

        # The maximum displacement is m-1, when a word is in the last
        # position m of the target sentence and the previously placed
        # word is in the first position.
        # Conversely, the minimum displacement is -(m-1).
        # Thus, the displacement range is (m-1) - (-(m-1)). Note that
        # displacement cannot be zero and is not included in the range.
        if max_m <= 1:
            initial_prob = IBMModel.MIN_PROB
        else:
            initial_prob = float(1) / (2 * (max_m - 1))
        if initial_prob < IBMModel.MIN_PROB:
            warnings.warn("A target sentence is too long (" + str(max_m) +
                          " words). Results may be less accurate.")

        src_classes = IBMModel4.get_unique_word_classes(self.src_classes)
        trg_classes = IBMModel4.get_unique_word_classes(self.trg_classes)

        for dj in range(1, max_m):
            for t_cls in trg_classes:
                self.non_head_distortion_table[dj][t_cls] = initial_prob
                self.non_head_distortion_table[-dj][t_cls] = initial_prob
                for s_cls in src_classes:
                    self.head_distortion_table[dj][s_cls][t_cls] = initial_prob
                    self.head_distortion_table[-dj][s_cls][t_cls] = initial_prob

    @classmethod
    def get_unique_word_classes(cls, word_classes_table):
        word_classes = set()
        for word_class in word_classes_table.values():
            word_classes.add(word_class)
        return word_classes

    @classmethod
    def longest_target_sentence_length(cls, sentence_aligned_corpus):
        max_m = 0
        for aligned_sentence in sentence_aligned_corpus:
            m = len(aligned_sentence.words)
            if m > max_m:
                max_m = m
        return max_m

    def train(self, parallel_corpus):
        # Reset all counts
        counts = Counts()

        for aligned_sentence in parallel_corpus:
            src_sentence = [None] + aligned_sentence.mots
            trg_sentence = ['UNUSED'] + aligned_sentence.words # 1-indexed
            m = len(aligned_sentence.words)

            # Sample the alignment space
            sampled_alignments = self.sample(src_sentence, trg_sentence)

            # E step (a): Compute normalization factors to weigh counts
            total_count = self.prob_of_alignments(sampled_alignments)

            # E step (b): Collect counts
            for alignment_info in sampled_alignments:
                count = self.prob_t_a_given_s(alignment_info)
                normalized_count = count / total_count
                counts.null = 0

                for j in range(1, m + 1):
                    counts.update_lexical_translation(
                        normalized_count, alignment_info, j)
                    counts.update_distortion(
                        normalized_count, alignment_info, j,
                        self.src_classes, self.trg_classes)

                counts.update_null_generation(normalized_count, alignment_info)
                counts.update_fertility(normalized_count, alignment_info)

        # M step: Update probabilities with maximum likelihood estimates
        # If any probability is less than MIN_PROB, clamp it to MIN_PROB
        existing_alignment_table = self.alignment_table
        self.reset_probabilities()
        # don't retrain alignment table
        self.alignment_table = existing_alignment_table

        self.maximize_lexical_translation_probabilities(counts)
        self.maximize_distortion_probabilities(counts)
        self.maximize_fertility_probabilities(counts)
        self.maximize_null_generation_probabilities(counts)

    def prob_of_alignments(self, alignments):
        probability = 0
        for alignment_info in alignments:
            probability += self.prob_t_a_given_s(alignment_info)
        return probability

    def prob_t_a_given_s(self, alignment_info):
        """
        Probability of target sentence and an alignment given the
        source sentence
        """
        probability = 1.0
        MIN_PROB = IBMModel.MIN_PROB

        def null_generation_term():
            # Binomial distribution: B(m - null_fertility, p1)
            value = 1.0
            p1 = self.p1
            p0 = 1 - p1
            null_fertility = alignment_info.fertility_of_i(0)
            m = len(alignment_info.trg_sentence) - 1
            value *= (pow(p1, null_fertility) * pow(p0, m - 2 * null_fertility))
            if value < MIN_PROB:
                return MIN_PROB

            # Combination: (m - null_fertility) choose null_fertility
            for i in range(1, null_fertility + 1):
                value *= (m - null_fertility - i + 1) / i
            return value

        def fertility_term():
            value = 1.0
            src_sentence = alignment_info.src_sentence
            for i in range(1, len(src_sentence)):
                fertility = alignment_info.fertility_of_i(i)
                value *= (factorial(fertility) *
                          self.fertility_table[fertility][src_sentence[i]])
                if value < MIN_PROB:
                    return MIN_PROB
            return value

        def lexical_translation_term(j):
            t = alignment_info.trg_sentence[j]
            i = alignment_info.alignment[j]
            s = alignment_info.src_sentence[i]
            return self.translation_table[t][s]

        def distortion_term(j):
            t = alignment_info.trg_sentence[j]
            i = alignment_info.alignment[j]
            if i == 0:
                # case 1: t is aligned to NULL
                return 1.0
            elif alignment_info.is_head_word(j):
                # case 2: t is the first word of a tablet
                previous_cept = alignment_info.previous_cept(j)
                src_class = None
                if previous_cept is not None:
                    previous_s = alignment_info.src_sentence[previous_cept]
                    src_class = self.src_classes[previous_s]
                trg_class = self.trg_classes[t]
                dj = j - alignment_info.center_of_cept(previous_cept)
                return self.head_distortion_table[dj][src_class][trg_class]
            else:
                # case 3: t is a subsequent word of a tablet
                previous_position = alignment_info.previous_in_tablet(j)
                trg_class = self.trg_classes[t]
                dj = j - previous_position
                return self.non_head_distortion_table[dj][trg_class]
        # end nested functions

        # Abort computation whenever probability falls below MIN_PROB at
        # any point, since MIN_PROB can be considered as zero
        probability *= null_generation_term()
        if probability < MIN_PROB:
            return MIN_PROB

        probability *= fertility_term()
        if probability < MIN_PROB:
            return MIN_PROB

        for j in range(1, len(alignment_info.trg_sentence)):
            probability *= lexical_translation_term(j)
            if probability < MIN_PROB:
                return MIN_PROB

            probability *= distortion_term(j)
            if probability < MIN_PROB:
                return MIN_PROB

        return probability

    def maximize_lexical_translation_probabilities(self, counts):
        for t, src_words in counts.t_given_s.items():
            for s in src_words:
                estimate = counts.t_given_s[t][s] / counts.any_t_given_s[s]
                self.translation_table[t][s] = max(estimate, IBMModel.MIN_PROB)

    def maximize_distortion_probabilities(self, counts):
        head_d_table = self.head_distortion_table
        for dj, src_classes in counts.head_distortion.items():
            for s_cls, trg_classes in src_classes.items():
                for t_cls in trg_classes:
                    estimate = (counts.head_distortion[dj][s_cls][t_cls] /
                                counts.head_distortion_for_any_dj[s_cls][t_cls])
                    head_d_table[dj][s_cls][t_cls] = max(estimate,
                                                         IBMModel.MIN_PROB)

        non_head_d_table = self.non_head_distortion_table
        for dj, trg_classes in counts.non_head_distortion.items():
            for t_cls in trg_classes:
                estimate = (counts.non_head_distortion[dj][t_cls] /
                            counts.non_head_distortion_for_any_dj[t_cls])
                non_head_d_table[dj][t_cls] = max(estimate, IBMModel.MIN_PROB)

    def maximize_fertility_probabilities(self, counts):
        for fertility, src_words in counts.fertility.items():
            for s in src_words:
                estimate = (counts.fertility[fertility][s] /
                            counts.fertility_for_any_phi[s])
                self.fertility_table[fertility][s] = max(estimate,
                                                         IBMModel.MIN_PROB)

    def maximize_null_generation_probabilities(self, counts):
        MIN_PROB = IBMModel.MIN_PROB
        p1_estimate = counts.p1 / (counts.p1 + counts.p0)
        p1_estimate = max(p1_estimate, MIN_PROB)
        # Clip p1 if it is too large, because p0 = 1 - p1 should not be
        # smaller than MIN_PROB
        self.p1 = min(p1_estimate, 1 - MIN_PROB)


class Counts(object):
    """
    Data object to store counts of various parameters during training
    """
    def __init__(self):
        self.t_given_s = defaultdict(lambda: defaultdict(lambda: 0.0))
        self.any_t_given_s = defaultdict(lambda: 0.0)

        self.head_distortion = defaultdict(
            lambda: defaultdict(lambda: defaultdict(lambda: 0.0)))
        self.head_distortion_for_any_dj = defaultdict(
            lambda: defaultdict(lambda: 0.0))
        self.non_head_distortion = defaultdict(
            lambda: defaultdict(lambda: 0.0))
        self.non_head_distortion_for_any_dj = defaultdict(lambda: 0.0)

        self.p0 = 0.0
        self.p1 = 0.0

        self.fertility = defaultdict(lambda: defaultdict(lambda: 0.0))
        self.fertility_for_any_phi = defaultdict(lambda: 0.0)

        self.null = 0

    def update_lexical_translation(self, count, alignment_info, j):
        i = alignment_info.alignment[j]
        t = alignment_info.trg_sentence[j]
        s = alignment_info.src_sentence[i]
        self.t_given_s[t][s] += count
        self.any_t_given_s[s] += count

    def update_distortion(self, count, alignment_info, j,
                          src_classes, trg_classes):
        i = alignment_info.alignment[j]
        t = alignment_info.trg_sentence[j]
        if i == 0:
            # case 1: t is aligned to NULL
            self.null += 1
        elif alignment_info.is_head_word(j):
            # case 2: t is the first word of a tablet
            previous_cept = alignment_info.previous_cept(j)
            if previous_cept is not None:
                previous_src_word = alignment_info.src_sentence[previous_cept]
                src_class = src_classes[previous_src_word]
            else:
                src_class = None
            trg_class = trg_classes[t]
            dj = j - alignment_info.center_of_cept(previous_cept)
            self.head_distortion[dj][src_class][trg_class] += count
            self.head_distortion_for_any_dj[src_class][trg_class] += count
        else:
            # case 3: t is a subsequent word of a tablet
            previous_j = alignment_info.previous_in_tablet(j)
            trg_class = trg_classes[t]
            dj = j - previous_j
            self.non_head_distortion[dj][trg_class] += count
            self.non_head_distortion_for_any_dj[trg_class] += count

    def update_null_generation(self, count, alignment_info):
        m = len(alignment_info.trg_sentence) - 1
        self.p1 += self.null * count
        self.p0 += (m - 2 * self.null) * count

    def update_fertility(self, count, alignment_info):
        for i in range(0, len(alignment_info.src_sentence)):
            s = alignment_info.src_sentence[i]
            fertility = len(alignment_info.cepts[i])
            self.fertility[fertility][s] += count
            self.fertility_for_any_phi[s] += count


# run doctests
if __name__ == "__main__":
    import doctest
    doctest.testmod()