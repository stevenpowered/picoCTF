""" Module for interacting with the achievements """

import imp
import pymongo

import api

from functools import wraps
from os.path import join
from datetime import datetime
from voluptuous import Schema, Required, Range
from api.common import check, InternalException, SevereInternalException, validate, safe_fail, WebException

processor_base_path = "./processors"

achievement_schema = Schema({
    Required("name"): check(
        ("The achievement's display name must be a string.", [str])),
    Required("score"): check(
        ("Score must be a positive integer.", [int, Range(min=0)])),
    Required("event"): check(
        ("Type must be a string.", [str])),
    Required("description"): check(
        ("The description must be a string.", [str])),
    Required("processor"): check(
        ("The processor path must be a string.", [str])),
    Required("hidden"): check(
        ("An achievement's hidden state is either True or False.", [
            lambda hidden: type(hidden) == bool])),
    Required("image"): check(
        ("An achievement's image path must be a string.", [str])),
    "disabled": check(
        ("An achievement's disabled state is either True or False.", [
            lambda disabled: type(disabled) == bool])),
    "aid": check(
        ("You should not specify a aid for an achievement.", [lambda _: False])),
    "_id": check(
        ("Your achievements should not already have _ids.", [lambda id: False]))
})

def get_all_events(show_disabled=False):
    """
    Gets the set of distinct achievement events.

    Args:
        show_disabled: Whether to include events that are only on disabled achievements
    Returns:
        The set of distinct achievement events.
    """

    db = api.common.get_conn()

    match = {}
    if not show_disabled:
        match.update({"disabled": False})

    return db.achievemets.find(match).distinct("event")

def get_achievement(aid=None, name=None, show_disabled=False):
    """
    Gets a single achievement

    Args:
        aid: the achievement id
        name: the name of the achievement
        show_disabled: Boolean indicating whether or not to show disabled achievements.
    """

    db = api.common.get_conn()

    match = {}

    if aid is not None:
        match.update({'aid': aid})
    elif name is not None:
        match.update({'name': name})
    else:
        raise InternalException("Must supply aid or display name")

    if not show_disabled:
        match.update({"disabled": False})

    db = api.common.get_conn()
    achievement = db.achievements.find_one(match, {"_id":0})

    if achievement is None:
        raise SevereInternalException("Could not find achievement! You gave " + str(match))

    return achievement

def get_all_achievements(event=None, show_disabled=False):
    """
    Gets all of the achievements in the database.

    Args:
        event: Optional parameter to restrict which achievements are returned
        show_disabled: Boolean indicating whether or not to show disabled achievements.
    Returns:
        List of achievements from the database
    """

    db = api.common.get_conn()

    match = {}
    if event is not None:
        match.update({'event': event})

    if not show_disabled:
        match.update({'disabled': False})

    return list(db.achievements.find(match, {"_id":0}).sort('score', pymongo.ASCENDING))

def get_earned_achievement_entries(tid=None, uid=None, aid=None):
    """
    Gets the solved achievements for a given team or user.

    Args:
        tid: The team id
        event: Optional parameter to restrict which achievements are returned
    Returns:
        List of solved achievements
    """

    db = api.common.get_conn()

    match = {}

    if uid is not None:
        match.update({"uid": uid})
    elif tid is not None:
        match.update({"tid": tid})

    if aid is not None:
        match.update({"aid": aid})

    return list(db.earned_achievements.find(match, {"_id":0}))

def get_earned_aids(tid=None, uid=None, aid=None):
    """
    Gets the solved aids for a given team or user.

    Args:
        tid: The team id
        event: Optional parameter to restrict which achievements are returned
    Returns:
        List of solved achievement ids
    """

    return [a["aid"] for a in get_earned_achievement_entries(tid=tid, uid=uid, aid=aid)]

def set_earned_achievements_seen(tid=None, uid=None):
    """
    Sets all earned achievements from a team or user seen.

    Args:
        tid: the team id
        uid: the user id
    """

    db = api.common.get_conn()

    match = {}

    if tid is not None:
        match.update({"tid": tid})
    elif uid is not None:
        match.update({"uid": uid})
    else:
        raise InternalException("You must specify either a tid or uid")

    db.earned_achievements.update(match, {"$set": {"seen": True}}, multi=True)

def get_earned_achievements_display(tid=None, uid=None):
    """
    Gets the achievement display for a given user/team.

    Args:
        tid: The team id
        tid: The user id
    Returns:
        A list of enabled achievements the team has earned.
    """

    #TODO: info leak
    achievements = [get_achievement(aid=achievement["aid"]) for achievement in get_earned_achievement_entries(tid=tid, uid=uid)]

    return achievements

def get_earned_achievements(tid=None, uid=None):
    """
    Gets the solved achievements for a given team or user.

    Args:
        tid: The team id
        tid: The user id
    Returns:
        List of solved achievement dictionaries
    """

    #TODO: Evaluate which fields are sensitive.

    achievements = get_earned_achievement_entries(tid=tid, uid=uid)
    set_earned_achievements_seen(tid=tid, uid=uid)

    for achievement in achievements:
        achievement.update(get_achievement(aid=achievement["aid"]))
        achievement.pop("data")

    return achievements

def reevaluate_earned_achievements(aid):
    """
    In the case of the achievement or processor being updated, this will reevaluate earned achievements for an achievement.

    Args:
        aid: the aid of the achievement to be reevaluated.
    """

    db = api.common.get_conn()

    get_achievement(aid=aid, show_disabled=True)

    keys = []
    for earned_achievement in get_earned_achievements():
        if not process_achievement(aid, data=earned_achievement["data"]):
            keys.append({"aid": aid, "tid":earned_achievement["tid"]})

    db.earned_achievements.remove({"$or": keys})

def reevaluate_all_earned_acheivements():
    """
    In the case of the achievement or processor being updated, this will reevaluate all earned achievements.
    """

    api.cache.clear_all()
    for achievement in get_earned_achievements():
        reevaluate_earned_achievements(achievement["aid"])

def set_achievement_disabled(aid, disabled):
    """
    Updates a achievement's availability.

    Args:
        aid: the achievement's aid
        disabled: whether or not the achievement should be disabled.
    Returns:
        The updated achievement object.
    """

def get_processor(aid):
    """
    Returns the processor module for a given achievement.

    Args:
        aid: the achievement id
    Returns:
        The processor module
    """

    try:
        path = get_achievement(aid=aid, show_disabled=True)["grader"]
        return imp.load_source(path[:-3], join(achievement_base_path, path))
    except FileNotFoundError:
        raise InternalException("Achievement processor is offline.")

def process_achievement(aid, data):
    """
    Determines whether or not an achievement has been earned.

    Args:
        aid: the achievement id
        data: additional data dictionary
    """

    if data.get("uid", None) is None:
        data["uid"] = api.user.get_user()["uid"]

    if data.get("tid", None) is None:
        data["tid"] = api.user.get_user(uid=data["uid"])["tid"]

    get_achievement(aid=aid, show_disabled=True)
    processor = get_processor(aid)

    return processor.process(api, data)

def insert_earned_achievement(aid, data):
    """
    Store earned achievement for a user/team.

    Args:
        aid: the achievement id
        data: the data necessary to assess the achievement
              must include tid, uid
    """

    db = api.common.get_conn()

    tid, uid = data.get("tid"), data.get("uid")

    db.earned_achievements.insert({
        "aid": aid,
        "tid": tid,
        "uid": uid,
        "data": data,
        "timestamp": datetime.utcnow(),
        "seen": False
    })

def process_achievements(event, data):
    """
    Process achievements of a type with data.

    Args:
        event: event type, e.g., submit
        data: dictionary with additional information necessary for assesment
    """

    if data.get("uid", None) is None:
        data["uid"] = api.user.get_user()["uid"]

    if data.get("tid", None) is None:
        data["tid"] = api.user.get_user(uid=data["uid"])["tid"]

    eligible_achievements = [
        achievement for achievement in get_all_achievements(event=event) \
            if achievement not in get_earned_achievements(tid=data["tid"])]

    for achievement in eligible_achievements:
        aid = achievement["aid"]

        if process_achievement(aid, data):
            insert_earned_achievement(aid, data)

def insert_achievement(achievement):
    """
    Inserts an achievement object into the database.

    Args:
        achievement: the achievement object loaded from json.
    Returns:
        The achievment's aid.
    """

    db = api.common.get_conn()
    validate(achievement_schema, achievement)

    achievement["disabled"] = achievement.get("disabled", False)

    achievement["aid"] = api.common.hash(achievement["name"])

    if safe_fail(get_achievement, aid=achievement["aid"]) is not None:
        raise WebException("achievement with identical aid already exists.")

    if safe_fail(get_achievement, name=achievement["name"]) is not None:
        raise WebException("achievement with identical name already exists.")

    db.achievements.insert(achievement)
    api.cache.fast_cache.clear()

    return achievement["aid"]

def update_achievement(aid, updated_achievement):
    """
    Updates a achievement with new properties.

    Args:
        aid: the aid of the achievement to update.
        updated_achievement: an updated achievement object.
    Returns:
        The updated achievement object.
    """

    db = api.common.get_conn()

    if updated_achievement.get("name", None) is not None:
        if safe_fail(get_achievement, name=updated_achievement["name"]) is not None:
            raise WebException("Achievement with identical name already exists.")

    achievement = get_achievement(aid=aid, show_disabled=True).copy()
    achievement.update(updated_achievement)

    # pass validation by removing/readding aid
    achievement.pop("aid")
    validate(achievement_schema, achievement)
    achievement["aid"] = aid



    db.achievements.update({"aid": aid}, achievement)
    api.cache.fast_cache.clear()

    return achievement
