# -*- coding:utf-8 -*-

from userManage.models import AdminGroup,UserOperatorRecord
from MagicStack.api import *
from MagicStack.settings import BASE_DIR
import functools
from emergency.emer_api import send_email
from emergency.models import EmergencyEvent, EmergencyRules

def group_add_user(group, user_id=None, username=None):
    """
    用户组中添加用户
    UserGroup Add a user
    """
    if user_id:
        user = get_object(User, id=user_id)
    else:
        user = get_object(User, username=username)

    if user:
        group.user_set.add(user)


def db_add_group(**kwargs):
    """
    add a user group in database
    数据库中添加用户组
    """
    name = kwargs.get('name')
    group = get_object(UserGroup, name=name)
    users = kwargs.pop('users_id')

    if not group:
        group = UserGroup(**kwargs)
        group.save()
        for user_id in users:
            group_add_user(group, user_id)


def group_update_member(group_id, users_id_list):
    """
    user group update member
    用户组更新成员
    """
    group = get_object(UserGroup, id=group_id)
    if group:
        group.user_set.clear()
        for user_id in users_id_list:
            user = get_object(UserGroup, id=user_id)
            if isinstance(user, UserGroup):
                group.user_set.add(user)


def db_add_user(**kwargs):
    """
    add a user in database
    数据库中添加用户
    """
    groups_post = kwargs.pop('groups')
    admin_groups = kwargs.pop('admin_groups')
    role = kwargs.get('role', 'CU')
    user = User(**kwargs)
    user.set_password(kwargs.get('password'))
    user.save()
    if groups_post:
        group_select = []
        for group_id in groups_post:
            group = UserGroup.objects.filter(id=group_id)
            group_select.extend(group)
        user.group = group_select
        user.save()

    if admin_groups and role == 'GA':  # 如果是组管理员就要添加组管理员和组到管理组中
        for group_id in admin_groups:
            group = get_object(UserGroup, id=group_id)
            if group:
                AdminGroup(user=user, group=group).save()
    return user


def db_update_user(**kwargs):
    """
    update a user info in database
    数据库更新用户信息
    """
    groups_post = kwargs.pop('groups')
    admin_groups_post = kwargs.pop('admin_groups')
    user_id = kwargs.pop('user_id')
    password = kwargs.pop('password')
    user = User.objects.filter(id=user_id)
    if user:
        user.update(**kwargs)
        user_get = user[0]
        if password.strip():
            user_get.set_password(password)
            user_get.save()
    else:
        return None

    group_select = []
    if groups_post:
        for group_id in groups_post:
            group = UserGroup.objects.filter(id=group_id)
            group_select.extend(group)
    user_get.group = group_select

    if admin_groups_post != '':
        user_get.admingroup_set.all().delete()
        for group_id in admin_groups_post:
            group = get_object(UserGroup, id=group_id)
            AdminGroup(user=user, group=group).save()
    user_get.save()


def db_del_user(username):
    """
    delete a user from database
    从数据库中删除用户
    """
    user = get_object(User, username=username)
    if user:
        user.delete()


def gen_ssh_key(username, password='',
                key_dir=os.path.join(KEY_DIR, 'user'),
                authorized_keys=True, home="/home", length=2048):
    """
    generate a user ssh key in a property dir
    生成一个用户ssh密钥对
    """
    logger.debug('生成ssh key， 并设置authorized_keys')
    private_key_file = os.path.join(key_dir, username+'.pem')
    mkdir(key_dir, mode=0777)
    if os.path.isfile(private_key_file):
        os.unlink(private_key_file)
    ret = bash('echo -e  "y\n"|ssh-keygen -t rsa -f %s -b %s -P "%s"' % (private_key_file, length, password))

    if authorized_keys:
        auth_key_dir = os.path.join(home, username, '.ssh')
        mkdir(auth_key_dir, username=username, mode=0700)
        authorized_key_file = os.path.join(auth_key_dir, 'authorized_keys')
        with open(private_key_file+'.pub') as pub_f:
            with open(authorized_key_file, 'w') as auth_f:
                auth_f.write(pub_f.read())
        os.chmod(authorized_key_file, 0600)
        chown(authorized_key_file, username)


def server_add_user(username, ssh_key_pwd=''):
    """
    add a system user in jumpserver
    在jumpserver服务器上添加一个用户
    """
    bash("useradd -s '%s' '%s'" % (os.path.join(BASE_DIR, 'init.sh'), username))
    gen_ssh_key(username, ssh_key_pwd)


def user_add_mail(user, default_email, kwargs):
    """
    add user send mail
    发送用户添加邮件
    """
    user_role = {'SU': u'超级管理员', 'GA': u'组管理员', 'CU': u'普通用户'}
    mail_title = u'恭喜你!用户 %s 已成功添加至MagicStack,您可以用此账户登录MagicStack' % user.name
    mail_msg = u"""
    Hi, %s
        您的用户名： %s
        您的权限： %s
        您的web登录密码： %s
        感谢您使用MagicStack,谢谢!
    """ % (user.name, user.username, user_role.get(user.role, u'普通用户'),
           kwargs.get('password'))
    rest_send_mail = send_email(default_email, mail_title, [user.email], mail_msg)
    if rest_send_mail['msgCode'] == 1:
        return False
    return True



def server_del_user(username):
    """
    删除系统上的某用户
    """
    bash('userdel -r -f %s' % username)


def get_display_msg(user, password='', send_mail_need=False):
    if send_mail_need:
        msg = u'添加用户 %s 成功！ 用户密码已发送到 %s 邮箱！' % (user.name, user.email)
    else:
        msg = u"""
        用户名：%s <br />
        密码：%s <br />
        该账号密码可以登陆MagicStack
        """ % (user.username, password)
    return msg


def user_operator_record(func):
    """
    用户操作记录
    operator: add edit delete
    flag: success/false
    content: the result of the operator
    告警记录
    emer_content: emergency source
    emer_status: the content of the emergency
    """
    res = {'operator':'', 'flag':'success', 'content':'', 'emer_content':'', 'emer_status': ''}
    @functools.wraps(func)
    def wrapper(request, *args):
        response = func(request,res,*args)
        if request.method == 'POST':
            logger.debug('用户操作记录:')
            user_record = UserOperatorRecord()
            start_time = datetime.datetime.now()
            user_record.username = request.user.username
            user_record.operator = res['operator']
            user_record.op_time = start_time
            user_record.content = res['content']
            user_record.result = res['flag']
            logger.info(res['content'])
            user_record.save()
            logger.debug('用户操作记录写入成功！')

            if res['emer_content'] in [1, 6, 7]:
                logger.info('告警事件记录:')
                emer_event = EmergencyEvent()
                emer_event.emer_time = datetime.datetime.now()
                emer_event.emer_user = request.user.username
                emer_event.emer_event = EmergencyRules.objects.get(content=res['emer_content'])
                emer_event.emer_info = res['emer_status']
                logger.info(res['emer_status'])
                emer_event.save()
                logger.info('告警事件写入成功!')
        return response
    return wrapper
