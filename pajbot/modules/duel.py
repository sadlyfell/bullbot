import logging

from numpy import random

import pajbot.exc
from pajbot import utils
from pajbot.managers.db import DBManager
from pajbot.models.command import Command
from pajbot.models.command import CommandExample
from pajbot.models.duel import DuelManager
from pajbot.modules import BaseModule
from pajbot.modules import ModuleSetting

log = logging.getLogger(__name__)


class DuelModule(BaseModule):

    ID = __name__.split(".")[-1]
    NAME = "Duel (mini game)"
    DESCRIPTION = "Let players duel to win or lose points."
    CATEGORY = "Game"
    SETTINGS = [
        ModuleSetting(
            key="message_won",
            label="Winner message | Available arguments: {winner}, {loser}",
            type="text",
            required=True,
            placeholder="{winner} won the duel vs {loser} PogChamp",
            default="{winner} won the duel vs {loser} PogChamp",
            constraints={"min_str_len": 10, "max_str_len": 400},
        ),
        ModuleSetting(
            key="message_won_points",
            label="Points message | Available arguments: {winner}, {loser}, {total_pot}, {extra_points}",
            type="text",
            required=True,
            placeholder="{winner} won the duel vs {loser} PogChamp . The pot was {total_pot}, the winner gets their bet back + {extra_points} points",
            default="{winner} won the duel vs {loser} PogChamp . The pot was {total_pot}, the winner gets their bet back + {extra_points} points",
            constraints={"min_str_len": 10, "max_str_len": 400},
        ),
        ModuleSetting(
            key="online_global_cd",
            label="Global cooldown (seconds)",
            type="number",
            required=True,
            placeholder="",
            default=0,
            constraints={"min_value": 0, "max_value": 120},
        ),
        ModuleSetting(
            key="online_user_cd",
            label="Per-user cooldown (seconds)",
            type="number",
            required=True,
            placeholder="",
            default=5,
            constraints={"min_value": 0, "max_value": 240},
        ),
        ModuleSetting(
            key="show_on_clr", label="Show duels on the clr overlay", type="boolean", required=True, default=True
        ),
    ]

    def load_commands(self, **options):
        self.commands["duel"] = Command.raw_command(
            self.initiate_duel,
            delay_all=self.settings["online_global_cd"],
            delay_user=self.settings["online_user_cd"],
            description="Initiate a duel with a user",
            examples=[
                CommandExample(
                    None,
                    "0-point duel",
                    chat="user:!duel Karl_Kons\n" "bot>user:You have challenged Karl_Kons for 0 points",
                    description="Duel Karl_Kons for 0 points",
                ).parse(),
                CommandExample(
                    None,
                    "69-point duel",
                    chat="user:!duel Karl_Kons 69\n" "bot>user:You have challenged Karl_Kons for 69 points",
                    description="Duel Karl_Kons for 69 points",
                ).parse(),
            ],
        )
        self.commands["cancelduel"] = Command.raw_command(
            self.cancel_duel, delay_all=0, delay_user=10, description="Cancel your duel request"
        )
        self.commands["accept"] = Command.raw_command(
            self.accept_duel, delay_all=0, delay_user=0, description="Accept a duel request"
        )
        self.commands["decline"] = Command.raw_command(
            self.decline_duel, delay_all=0, delay_user=0, description="Decline a duel request"
        )
        self.commands["deny"] = self.commands["decline"]
        self.commands["duelstatus"] = Command.raw_command(
            self.status_duel, delay_all=0, delay_user=5, description="Current duel request info"
        )
        self.commands["duelstats"] = Command.raw_command(
            self.get_duel_stats, delay_all=0, delay_user=120, description="Get your duel statistics"
        )

    def __init__(self, bot):
        super().__init__(bot)
        self.duel_requests = {}
        self.duel_request_price = {}
        self.duel_targets = {}
        self.blUsers = ["admiralbulldog", "infinitegachi"]

    def initiate_duel(self, **options):
        """
        Initiate a duel with a user.
        You can also bet points on the winner.
        By default, the maximum amount of points you can spend is 420.

        How to add: !add funccommand duel initiate_duel --cd 0 --usercd 5
        How to use: !duel USERNAME POINTS_TO_BET
        """

        bot = options["bot"]
        source = options["source"]
        message = options["message"]

        if message is None:
            return False

        msg_split = message.split()
        username = msg_split[0]
        user = bot.users.find(username)
        duel_price = 300
        if user is None:
            # No user was found with this username
            return False

        if len(msg_split) > 1:
            try:
                duel_price = pajbot.utils.parse_points_amount(source, msg_split[1])
                if duel_price < 300:
                    bot.whisper(source.username, "You may only duel for 300+ points, no pussy")
                    bot.whisper(
                        user.username,
                        "{} tried to duel you for less than 300 points. What a "
                        "cheapskate EleGiggle".format(source.username_raw),
                    )
                    return False

            except pajbot.exc.InvalidPointAmount as e:
                bot.whisper(user.username, str(e))
                return False

        if source.username in self.duel_requests:
            bot.whisper(
                source.username,
                "You already have a duel request active with {}. Type !cancelduel to cancel your duel request.".format(
                    self.duel_requests[source.username]
                ),
            )
            return False

        if user == source:
            # You cannot duel yourself
            return False

        if user.username in self.blUsers:
            return True

        if user.last_active is None or (utils.now() - user._last_active).total_seconds() > 5 * 60:
            bot.whisper(
                source.username,
                "This user has not been active in chat within the last 5 minutes. Get them to type in chat before sending another challenge",
            )
            return False

        if not user.can_afford(duel_price) or not source.can_afford(duel_price):
            bot.whisper(
                source.username,
                "You or your target do not have more than {} points, therefore you cannot duel for that amount.".format(
                    duel_price
                ),
            )
            return False

        if user.username in self.duel_targets:
            bot.whisper(
                source.username,
                "This person is already being challenged by {}. Ask them to answer the offer by typing !deny or !accept".format(
                    self.duel_targets[user.username]
                ),
            )
            return False

        self.duel_targets[user.username] = source.username
        self.duel_requests[source.username] = user.username
        self.duel_request_price[source.username] = duel_price
        bot.whisper(
            user.username,
            "You have been challenged to a duel by {} for {} points. You can either !accept or !deny this challenge.".format(
                source.username_raw, duel_price
            ),
        )
        bot.whisper(source.username, "You have challenged {} for {} points".format(user.username_raw, duel_price))
        bot.execute_delayed(60, self.time_expired, (source.username, user.username, bot))

    def time_expired(self, initiator, target, bot):
        if target in self.duel_targets and initiator in self.duel_requests:
            del self.duel_targets[self.duel_requests[initiator]]
            del self.duel_requests[initiator]

            bot.whisper(initiator, "Your duel request against {} has expired. Ditched OMEGALUL".format(target))
            bot.whisper(target, "Chu ignoring {} for, his duel request against you expired cmonBruh".format(initiator))

    def cancel_duel(self, **options):
        """
        Cancel any duel requests you've sent.

        How to add: !add funccomand cancelduel|duelcancel cancel_duel --cd 0 --usercd 10
        How to use: !cancelduel
        """

        bot = options["bot"]
        source = options["source"]

        if source.username not in self.duel_requests:
            bot.whisper(source.username, "You have not sent any duel requests")
            return

        bot.whisper(source.username, "You have cancelled the duel vs {}".format(self.duel_requests[source.username]))

        del self.duel_targets[self.duel_requests[source.username]]
        del self.duel_requests[source.username]

    def accept_duel(self, **options):
        """
        Accepts any active duel requests you've received.

        How to add: !add funccommand accept accept_duel --cd 0 --usercd 0
        How to use: !accept
        """

        bot = options["bot"]
        source = options["source"]

        if source.username not in self.duel_targets:
            bot.whisper(source.username, "You are not being challenged to a duel by anyone.")
            return

        requestor = bot.users[self.duel_targets[source.username]]
        duel_price = self.duel_request_price[self.duel_targets[source.username]]

        if not source.can_afford(duel_price) or not requestor.can_afford(duel_price):
            bot.whisper(
                source.username,
                "Your duel request with {} was cancelled due to one of you not having enough points.".format(
                    requestor.username_raw
                ),
            )
            bot.whisper(
                requestor.username,
                "Your duel request with {} was cancelled due to one of you not having enough points.".format(
                    source.username_raw
                ),
            )

            del self.duel_requests[self.duel_targets[source.username]]
            del self.duel_targets[source.username]

            return False

        source.points -= duel_price
        requestor.points -= duel_price
        participants = [source, requestor]
        winner = random.choice(participants)
        participants.remove(winner)
        loser = participants.pop()
        winner.points += duel_price * 2

        winner.save()
        loser.save()

        DuelManager.user_won(winner, duel_price * 2)
        DuelManager.user_lost(loser, duel_price)

        arguments = {"winner": winner.username, "loser": loser.username, "total_pot": duel_price}

        message = self.get_phrase("message_won_points", **arguments)

        bot.say(message)

        del self.duel_requests[self.duel_targets[source.username]]
        del self.duel_targets[source.username]

    def decline_duel(self, **options):
        """
        Declines any active duel requests you've received.

        How to add: !add funccommand deny|decline decline_duel --cd 0 --usercd 0
        How to use: !decline
        """

        bot = options["bot"]
        source = options["source"]

        if source.username not in self.duel_targets:
            bot.whisper(source.username, "You are not being challenged to a duel")
            return False

        requestor_username = self.duel_targets[source.username]

        bot.whisper(source.username, "You have declined the duel vs {}".format(requestor_username))
        bot.whisper(requestor_username, "{} declined the duel challenge with you.".format(source.username_raw))

        del self.duel_targets[source.username]
        del self.duel_requests[requestor_username]

    def status_duel(self, **options):
        """
        Whispers you the current status of your active duel requests/duel targets

        How to add: !add funccommand duelstatus|statusduel status_duel --cd 0 --usercd 5
        How to use: !duelstatus
        """

        bot = options["bot"]
        source = options["source"]

        msg = []
        if source.username in self.duel_requests:
            msg.append(
                "You have a duel request for {} points by {}".format(
                    self.duel_request_price[source.username], self.duel_requests[source.username]
                )
            )

        if source.username in self.duel_targets:
            msg.append(
                "You have a pending duel request from {} for {} points".format(
                    self.duel_targets[source.username], self.duel_request_price[self.duel_targets[source.username]]
                )
            )

        if len(msg) > 0:
            bot.whisper(source.username, ". ".join(msg))
        else:
            bot.whisper(
                source.username, "You have no duel request or duel target. Type !duel USERNAME POT to duel someone!"
            )

    @staticmethod
    def get_duel_stats(**options):
        """
        Whispers the users duel winratio to the user
        """

        bot = options["bot"]
        source = options["source"]

        with DBManager.create_session_scope(expire_on_commit=False) as db_session:
            db_session.add(source.user_model)

            if source.duel_stats is None:
                bot.whisper(source.username, "You have no recorded duels.")
                return True

            bot.whisper(
                source.username,
                "duels: {ds.duels_total} winrate: {ds.winrate:.2f}% streak: {ds.current_streak} profit: {ds.profit}".format(
                    ds=source.duel_stats
                ),
            )
